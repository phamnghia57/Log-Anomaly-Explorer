"""Real integration: demo-app -> ingestion -> OpenSearch -> worker -> local webhook.
Run from repository root: python -B clustering/evaluation/run_integration.py
Uses isolated indexes/ports, starts and stops only its own Python services.
Requires OpenSearch on localhost:9200 and dependencies of all three modules.
"""
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'clustering'))
from src.clustering import make_cluster_id
from precision_recall import evaluate


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def main():
    deadline = time.time() + 900
    while True:
        try:
            with httpx.Client(timeout=3, trust_env=False) as probe:
                if probe.get('http://127.0.0.1:9200').status_code == 200:
                    break
        except httpx.HTTPError:
            pass
        if time.time() > deadline:
            raise RuntimeError('OpenSearch did not become ready')
        print('Waiting for OpenSearch...', flush=True)
        time.sleep(15)
    run = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    output = Path(__file__).parent / 'integration' / run
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', STORAGE_BACKEND='opensearch',
               LOG_INDEX=f'integration-logs-{run}', QUARANTINE_INDEX=f'integration-quarantine-{run}',
               CLUSTER_INDEX=f'integration-clusters-{run}', OPENSEARCH_URL='http://127.0.0.1:9200',
               INGESTION_URL='http://127.0.0.1:18000/ingest', RETENTION_INTERVAL_SECONDS='0',
               WINDOW_SECONDS='30', HISTORY_WINDOWS='2', ANOMALY_THRESHOLD='2',
               ALERT_WEBHOOK_URL='http://127.0.0.1:18003/alert', ALERT_COOLDOWN_SECONDS='600')
    for port in (18000, 18001, 18003):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    hooks, processes, handles = [], [], []
    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):
            hooks.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 18003), Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = httpx.Client(timeout=30, trust_env=False)
    request_evidence = []
    try:
        for folder, port in [('ingestion', 18000), ('demo-app', 18001)]:
            handle = (output / f'{folder}.log').open('w', encoding='utf-8')
            handles.append(handle)
            processes.append(subprocess.Popen([sys.executable, '-B', '-m', 'uvicorn', 'src.main:app',
                '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT / folder, env=env,
                stdout=handle, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
            deadline = time.time() + 90
            while True:
                try:
                    response = client.get(f'http://127.0.0.1:{port}/health')
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.time() > deadline or processes[-1].poll() is not None:
                    raise RuntimeError(f'{folder} startup failed; inspect {output}')
                time.sleep(0.5)
            print(f'{folder}: healthy', flush=True)
        schema = json.loads((ROOT / 'docs/architect/contracts/cluster-record.schema.json').read_text())
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        start = math.ceil(time.time() / 30) * 30 + 1
        cases = [('web', 'value', 422, 'Simulated validation failure: required item data is invalid'),
                 ('web', 'connection', 502, 'Simulated connection failure: downstream dependency unreachable'),
                 ('web', 'runtime', 500, 'Simulated runtime failure'),
                 ('mobile-api', 'value', 422, 'Simulated validation failure: required item data is invalid'),
                 ('mobile-api', 'connection', 502, 'Simulated connection failure: downstream dependency unreachable'),
                 ('mobile-api', 'runtime', 500, 'Simulated runtime failure')]
        predictions, labels, observed_logs = [], [], []
        for window, repetitions in enumerate((1, 1, 6, 1)):
            window_start = start + window * 30
            time.sleep(max(0, window_start - time.time()))
            print(f'Window {window}: {repetitions} errors per signature', flush=True)
            for platform, fault, status, message in cases:
                for _ in range(repetitions):
                    params = dict(platform=platform, fault=fault, rate=1, seed=1)
                    response = client.get('http://127.0.0.1:18001/simulate-error', params=params)
                    assert response.status_code == status, response.text
                    request_evidence.append({'at': iso(time.time()), 'params': params, 'status': response.status_code})
            # Fault disabled: verify successful requests also reach ingestion.
            response = client.get('http://127.0.0.1:18001/simulate-error', params={'fault': 'runtime', 'rate': 0})
            assert response.status_code == 200
            end = math.floor(window_start / 30) * 30 + 30
            assert time.time() < end, 'Requests exceeded window: increase WINDOW_SECONDS'
            time.sleep(max(0, end + 1 - time.time()))
            client.post(f"http://127.0.0.1:9200/{env['LOG_INDEX']}/_refresh").raise_for_status()
            if window >= 2:
                command = subprocess.run([sys.executable, '-B', '-m', 'src.worker', '--window-to', iso(end)],
                    cwd=ROOT / 'clustering', env=env, capture_output=True, text=True, timeout=40)
                (output / f'worker-{window}.log').write_text(command.stdout + command.stderr, encoding='utf-8')
                assert command.returncode == 0, command.stderr
                response = client.get(f"http://127.0.0.1:9200/{env['CLUSTER_INDEX']}/_search", params={'size': 100})
                response.raise_for_status()
                records = [hit['_source'] for hit in response.json()['hits']['hits']]
                assert len(records) == 6
                for record in records:
                    validator.validate(record)
                    assert record['status'] == ('alerted' if window == 2 else 'normal'), record
                predictions.extend(records)
                if window == 2:
                    for platform, fault, _, message in cases:
                        service = 'demo-web' if platform == 'web' else 'demo-mobile-api'
                        labels.append(dict(incident_id=f'{run}-{platform}-{fault}', service=service,
                            window_from=iso(end-30), window_to=iso(end), expected_cluster_signature=message,
                            description=f'Real local fault injection: platform={platform}, fault={fault}, rate=1, seed=1; baseline 1/window then 6/window.'))
        response = client.get(f"http://127.0.0.1:9200/{env['LOG_INDEX']}/_search", params={'size': 1000})
        response.raise_for_status()
        observed_logs = [{'log_id': h['_id'], **h['_source']} for h in response.json()['hits']['hits']]
        assert len(observed_logs) == 58, len(observed_logs)
        for log in observed_logs:
            assert len(log['trace_id']) == 32 and int(log['trace_id'], 16) != 0
            assert len(log['span_id']) == 16 and int(log['span_id'], 16) != 0
        error_ids = {log['log_id'] for log in observed_logs if log['level'] == 'ERROR'}
        for record in predictions:
            assert set(record['log_ids']) <= error_ids
            assert set(record['trace_ids']) <= {log['trace_id'] for log in observed_logs}
        assert len(hooks) == 6, hooks
        label_path = output / 'labeled_incidents.json'
        label_path.write_text(json.dumps({'source': 'real local demo-app fault injection', 'incidents': labels}, indent=2), encoding='utf-8')
        metrics = evaluate(predictions, label_path, statuses=('alerted',))
        assert metrics['true_positive'] == 6 and metrics['false_positive'] == 0 and metrics['false_negative'] == 0
        for filename, data in [('predictions.json', predictions), ('logs.json', observed_logs),
                               ('webhooks.json', hooks), ('requests.json', request_evidence)]:
            (output / filename).write_text(json.dumps(data, indent=2), encoding='utf-8')
        report = dict(run_id=run, window_seconds=30, history_windows=2,
                      indexes={k: env[k] for k in ('LOG_INDEX', 'CLUSTER_INDEX', 'QUARANTINE_INDEX')},
                      logs=len(observed_logs), alerts=len(hooks), metrics=metrics,
                      checks=['six fault/platform combinations', 'baseline/spike/recovery', 'nonzero OTel trace/span',
                              'ClusterRecord schema', 'log/trace linkage', 'real local webhook delivery'])
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
        print(f'Evidence: {output}', flush=True)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=15)
        for handle in handles:
            handle.close()
        server.shutdown()
        server.server_close()
        client.close()


if __name__ == '__main__':
    main()
