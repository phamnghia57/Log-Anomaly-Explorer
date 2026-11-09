"""One browser persistence check using owned Docker data and the existing API harness."""

from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
from opensearchpy import OpenSearch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "query-api/tests")]
os.environ["STORAGE_BACKEND"] = "memory"  # Parent import only; APIProcess overrides all storage settings.
from test_assistant_undo_integration import APIProcess, CLUSTER, TIMESTAMP, history, seed


def save(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def command(name, argv, timeout=60, env=None):
    print(f"Running {name}", flush=True)
    result = subprocess.run(argv, cwd=ROOT / "web", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, env=env)
    text = "\n".join(line.rstrip() for line in result.stdout.decode("utf-8", errors="replace").splitlines()) + "\n"
    info = {"command": argv, "cwd": str(ROOT / "web"), "exit_code": result.returncode}
    (HERE / f"{name}.log").write_text(json.dumps(info, indent=2) + "\n\n" + text,
                                    encoding="utf-8", newline="\n")
    report["commands"].append(info)
    if result.returncode:
        raise RuntimeError(f"{name} exited {result.returncode}")
    return text.strip()


def free_port():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


report = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "commands": [],
          "python": sys.version, "opensearch-py": metadata.version("opensearch-py"),
          "result": "NOT VERIFIED", "backend_source_sha256": {
              p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
                  "query-api/src/assistant/router.py", "query-api/src/assistant/storage.py")}}


def main():
    owned_id = None
    vite = None
    vite_log = None
    run_id = uuid4().hex[:16]
    name = "vt013-frontend-" + run_id
    try:
        command("e2e-docker-version", ["docker", "version", "--format", "{{json .}}"])
        owned_id = command("e2e-opensearch-start", [
            "docker", "run", "-d", "--name", name, "--label", f"vt013.frontend={run_id}",
            "--publish", "127.0.0.1::9200", "--memory", "2g", "--ulimit", "nofile=65536:65536",
            "--tmpfs", "/usr/share/opensearch/data:rw,uid=1000,gid=1000,size=1g",
            "--env", "discovery.type=single-node", "--env", f"cluster.name={name}",
            "--env", "DISABLE_SECURITY_PLUGIN=true", "--env", "DISABLE_INSTALL_DEMO_CONFIG=true",
            "--env", "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m", "opensearchproject/opensearch:2.17.1",
        ])
        owned = json.loads(command("e2e-opensearch-inspect", ["docker", "inspect", owned_id]))[0]
        assert owned["Config"]["Labels"]["vt013.frontend"] == run_id
        assert owned["Name"] == "/" + name and not owned["HostConfig"]["Binds"]
        port = owned["NetworkSettings"]["Ports"]["9200/tcp"][0]
        assert port["HostIp"] == "127.0.0.1"
        url = f"http://127.0.0.1:{port['HostPort']}"
        with httpx.Client(trust_env=False, timeout=2) as client:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    response = client.get(url)
                    if response.status_code == 200:
                        info = response.json()
                        assert info["version"]["number"] == "2.17.1" and info["cluster_name"] == name
                        report["opensearch"] = info
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("Owned OpenSearch did not become ready")
        driver = OpenSearch(hosts=[url], timeout=10, max_retries=0)
        prefix = "vt013-frontend-" + run_id
        ns = SimpleNamespace(prefix=prefix, index=prefix + "-conversations",
                             password=secrets.token_urlsafe(24), secret=secrets.token_urlsafe(48),
                             instance=SimpleNamespace(client=driver, context={"url": url}, artifacts=HERE / "e2e-api"))
        ns.instance.artifacts.mkdir(exist_ok=True)
        driver.indices.create(index=prefix + "-clusters", body={"settings": {"number_of_shards": 1, "number_of_replicas": 0}})
        driver.create(index=prefix + "-clusters", id=CLUSTER, body={
            "cluster_id": CLUSTER, "log_ids": [], "trace_ids": [], "signature": "VT-013 disposable browser incident",
            "score": 3.0, "status": "anomalous", "first_seen": TIMESTAMP, "last_seen": TIMESTAMP,
        }, refresh="wait_for")
        original = history()
        original[-1]["content"] = "Original durable answer"
        seed(ns, original, legacy_mapping=True)
        save("e2e-before.persisted.json", driver.get(index=ns.index, id=CLUSTER))
        with APIProcess(ns) as api:
            web_url = f"http://127.0.0.1:{free_port()}"
            env = os.environ.copy()
            env.update(VITE_API_BASE_URL=str(api.client.base_url).rstrip("/"), VITE_JAEGER_URL="")
            argv = ["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", web_url.rsplit(":", 1)[1], "--strictPort"]
            report["vite_command"] = argv
            vite_log = (HERE / "e2e-vite.log").open("wb")
            vite = subprocess.Popen(argv, cwd=ROOT / "web", env=env, stdout=vite_log, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            with httpx.Client(trust_env=False, timeout=2) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if vite.poll() is not None:
                        raise RuntimeError("Owned Vite exited; see e2e-vite.log")
                    try:
                        if client.get(web_url).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Owned Vite readiness timeout")
            env.update(VT013_E2E_WEB_URL=web_url, VT013_E2E_API_URL=str(api.client.base_url).rstrip("/"),
                       VT013_E2E_PASSWORD=ns.password, VT013_E2E_PROOF=str(HERE / "e2e-browser-proof.json"))
            report["isolation"] = {"container_id": owned_id, "cluster_name": name, "url": url, "index_prefix": prefix,
                                   "api_url": str(api.client.base_url), "web_url": web_url}
            command("e2e-playwright", ["node", "node_modules/@playwright/test/cli.js", "test", "--config=playwright.vt013.config.ts"], timeout=120, env=env)
            final = driver.get(index=ns.index, id=CLUSTER)
            save("e2e-after.persisted.json", final)
            assert final["_source"]["messages"] == original
            assert final["_source"]["undo"] is None
            assert final["_source"]["created_at"] == TIMESTAMP
            proof = json.loads((HERE / "e2e-browser-proof.json").read_text(encoding="utf-8"))
            assert proof["reloaded"]["messages"] == original
            assert proof["reloaded"]["revision"] == f"{final['_primary_term']}:{final['_seq_no']}"
            report["result"] = "PASS"
            report["raw_persistence_assertions"] = "exact original messages, consumed snapshot, creation time, reload revision"
        driver.close()
    except Exception as error:
        report["failure_or_blocker"] = f"{type(error).__name__}: {error}"
        print(report["failure_or_blocker"], flush=True)
    finally:
        if vite is not None and vite.poll() is None:
            vite.terminate()
            try:
                vite.wait(timeout=10)
            except subprocess.TimeoutExpired:
                vite.kill()
                vite.wait(timeout=10)
        if vite_log is not None:
            vite_log.close()
        if owned_id:
            owned = json.loads(command("e2e-cleanup-ownership", ["docker", "inspect", owned_id]))[0]
            assert owned["Config"]["Labels"]["vt013.frontend"] == run_id
            command("e2e-opensearch-cleanup", ["docker", "rm", "-f", owned_id])
            report["owned_container_removed"] = True
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save("e2e-results.json", report)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
