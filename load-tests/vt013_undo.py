"""VT-013: real disposable persistence benchmark; no production tuning or tracing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from importlib import util, metadata
import json
import math
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
from threading import Barrier
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(os.environ.get("VT013_PERF_OUTPUT", str(ROOT / "docs/assignments/VT-013/evidence/performance")))
TIME = "2026-11-09T00:00:00+00:00"
TEXT = "đ" + "x" * 1022  # exactly 1024 UTF-8 bytes; deliberately compressible.


def turn(message):
    return [{"role": "user", "content": message, "created_at": TIME},
            {"role": "assistant", "content": TEXT, "created_at": TIME}]


def history(n):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": TEXT, "created_at": TIME} for i in range(n)]
    if n == 100:
        messages[1].update(content=None, tool_calls=[{"id": "call-1", "name": "get_cluster_history", "arguments": "{}"}])
        messages[2].update(role="tool", tool_call_id="call-1", name="get_cluster_history")
    return messages


def serve():
    sys.path[:0] = [str(ROOT), str(ROOT / "query-api/tests")]
    import vt013_integration_server as server
    server.turn = turn  # test-only deterministic AI; real routes/repository unchanged.
    server.serve()


def save(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def nearest(values, percentile):
    return sorted(values)[max(0, math.ceil(percentile * len(values)) - 1)] if values else None


def run():
    import httpx
    from opensearchpy import OpenSearch
    sys.path[:0] = [str(ROOT), str(ROOT / "query-api/tests")]
    os.environ["STORAGE_BACKEND"] = "memory"
    from test_assistant_undo_integration import APIProcess, storage
    HERE.mkdir(parents=True, exist_ok=True)
    assert not (HERE / "samples.jsonl").exists(), "Archive previous evidence before reproduction"
    sizes = [int(n) for n in os.environ.get("VT013_PERF_SIZES", "0,2,100").split(",")]
    assert sizes and len(set(sizes)) == len(sizes) and all(n in [0,2,100] for n in sizes)
    original = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in
        subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()}
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "commands": [], "classes": [],
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "python": sys.version, "platform": platform.platform(), "cpu_logical": os.cpu_count(),
        "packages": {p: metadata.version(p) for p in ["httpx", "opensearch-py", "fastapi", "uvicorn"]},
        "protocol": {"workers": 60, "warmup_rounds": 5, "measured_rounds": 50, "history_sizes": sizes,
            "percentile": "nearest rank across individual successful measured requests", "client_timeout_s": 40,
            "client_connections": 60, "client_keepalive": 60, "message_non_null_bytes": 1024,
            "api_workers": 1, "sdk_retries": "unchanged production defaults", "payload_compressible": True},
        "contention": [], "resource_samples": []}
    assert report["branch"] == "feat/vt013-undo-manhpd" and report["head"].startswith("d899b96")
    assert not subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT)
    owned = None
    driver = None
    tag = uuid4().hex[:16]
    prefix = "vt013-perf-" + tag

    def command(name, argv):
        p = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=90)
        r = {"command": argv, "exit_code": p.returncode}
        (HERE / (name + ".log")).write_text(json.dumps(r) + "\n" + p.stdout.decode(errors="replace") + p.stderr.decode(errors="replace"), encoding="utf-8")
        report["commands"].append(r)
        assert p.returncode == 0, name
        return p.stdout.decode().strip()

    def resources(api_pid):
        raw = command("resources-" + str(len(report["resource_samples"])), ["docker", "stats", "--no-stream", "--format", "{{json .}}", owned])
        report["resource_samples"].append({"utc": datetime.now(timezone.utc).isoformat(), "docker": json.loads(raw), "api_pid": api_pid})

    def path(cluster):
        return "/assistant/clusters/" + cluster + "/conversation"

    # Reuse reviewed server lifecycle/authentication without modifying that helper.
    popen = subprocess.Popen
    def launch(argv, *args, **kwargs):
        if isinstance(argv, list) and str(argv[-1]).endswith("vt013_integration_server.py"):
            argv = [*argv[:-1], str(Path(__file__).resolve()), "--serve"]
        return popen(argv, *args, **kwargs)

    try:
        command("docker-version", ["docker", "version", "--format", "{{json .}}"])
        command("host-resources", ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_ComputerSystem | Select-Object NumberOfLogicalProcessors,TotalPhysicalMemory | ConvertTo-Json"])
        owned = command("start", ["docker", "run", "-d", "--name", prefix, "--label", "vt013.performance=" + tag,
            "--publish", "127.0.0.1::9200", "--memory", "2g", "--ulimit", "nofile=65536:65536",
            "--tmpfs", "/usr/share/opensearch/data:rw,uid=1000,gid=1000,size=1g",
            "--env", "discovery.type=single-node", "--env", "cluster.name=" + prefix,
            "--env", "DISABLE_SECURITY_PLUGIN=true", "--env", "DISABLE_INSTALL_DEMO_CONFIG=true",
            "--env", "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m", "opensearchproject/opensearch:2.17.1"])
        info = json.loads(command("inspect", ["docker", "inspect", owned]))[0]
        assert info["Config"]["Labels"]["vt013.performance"] == tag and not info["HostConfig"]["Binds"]
        port = info["NetworkSettings"]["Ports"]["9200/tcp"][0]
        assert port["HostIp"] == "127.0.0.1"
        url = "http://127.0.0.1:" + port["HostPort"]
        driver = OpenSearch(hosts=[url], timeout=10, max_retries=0, pool_maxsize=60)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                node = driver.info()
                assert node["version"]["number"] == "2.17.1" and node["cluster_name"] == prefix
                report["opensearch"] = node
                break
            except Exception:
                time.sleep(.5)  # startup only, never synchronization or measured pacing.
        else:
            raise RuntimeError("Owned OpenSearch startup timeout")
        report["isolation"] = {"container_id": owned, "cluster_name": prefix, "index_prefix": prefix, "opensearch_url": url}
        ns = SimpleNamespace(prefix=prefix, index=prefix + "-conversations", password=secrets.token_urlsafe(24),
            secret=secrets.token_urlsafe(48), instance=SimpleNamespace(client=driver, context={"url":url}, artifacts=HERE / "api"))
        ns.instance.artifacts.mkdir()
        driver.indices.create(index=prefix + "-clusters", body={"settings":{"number_of_shards":1,"number_of_replicas":0}})
        def clusters(ids):
            body=[]
            for cid in ids:
                assert cid.startswith("vt013-")
                body += [{"create":{"_index":prefix + "-clusters","_id":cid}},
                    {"cluster_id":cid,"log_ids":[],"trace_ids":[],"signature":"isolated Undo benchmark", "score":3.,"status":"anomalous","first_seen":TIME,"last_seen":TIME}]
            assert not driver.bulk(body=body,refresh="wait_for")["errors"]
        with patch("subprocess.Popen", side_effect=launch), APIProcess(ns) as api:
            report["api_process"] = {"pid":api.process.pid,"command":[sys.executable,"-u","-B",str(Path(__file__).resolve()),"--serve"]}
            with httpx.Client(base_url=str(api.client.base_url),headers=dict(api.client.headers),timeout=40,trust_env=False,
                    limits=httpx.Limits(max_connections=60,max_keepalive_connections=60)) as client, ThreadPoolExecutor(max_workers=60) as pool, (HERE / "samples.jsonl").open("w",encoding="utf-8") as samples:
                for size in sizes:
                    ids=[f"vt013-{size}-{i:02}" for i in range(60)];clusters(ids);prior=history(size)
                    if size:
                        body=[]
                        for cid in ids:body += [{"create":{"_index":ns.index,"_id":cid}}, {"cluster_id":cid,"messages":prior,"created_at":TIME,"updated_at":TIME}]
                        assert not driver.bulk(body=body,refresh="wait_for")["errors"]
                    records=[];rounds=[];correct=0;aborted=None;resources(api.process.pid)
                    def prepare(cid):
                        r=client.post(path(cid)+"/messages",json={"message":TEXT});assert r.status_code==200
                        v=r.json();assert v["messages"]==prior+turn(TEXT) and v["undo_available"] is True
                        assert isinstance(v["revision"],str)
                        return cid,v["revision"]
                    for round_id in range(55):
                        eligible=list(pool.map(prepare,ids));barrier=Barrier(61,timeout=45)
                        def task(item):
                            cid,revision=item;barrier.wait();start=time.perf_counter();status=None;value=None;error=None
                            try:
                                response=client.post(path(cid)+"/undo",json={"expected_revision":revision});status=response.status_code;value=response.json()
                            except Exception as exc:error=type(exc).__name__
                            elapsed=(time.perf_counter()-start)*1000
                            return {"history_size":size,"round":round_id-5,"warmup":round_id<5,"cluster":cid,
                                "latency_ms":elapsed,"status":status,"error":error,
                                "response_bytes":len(response.content) if status is not None else None},value,revision
                        futures=[pool.submit(task,item) for item in eligible]
                        wall=time.perf_counter();barrier.wait();returned=[f.result(timeout=90) for f in futures];wall=time.perf_counter()-wall
                        def verify(item):
                            row,value,old=item;raw=driver.get(index=ns.index,id=row["cluster"])
                            ok=raw["_source"]["messages"]==prior and raw["_source"].get("undo")==None
                            if row["status"]==200:ok=ok and value["messages"]==prior and value["undo_available"] is False and value["revision"]!=old and value["revision"]==f"{raw['_primary_term']}:{raw['_seq_no']}"
                            row["persisted_correct"]=ok;row["expected_revision"]=old
                            row["restored_revision"]=value.get("revision") if isinstance(value,dict) else None
                            if not ok:save(f"incorrect-{size}-{round_id}-{row['cluster']}.json",raw)
                            return row
                        verified=list(pool.map(verify,returned));correct+=sum(x["persisted_correct"] for x in verified)
                        for row in verified:samples.write(json.dumps(row)+"\n")
                        samples.flush();rounds.append({"round":round_id,"wall_seconds":wall,"success":sum(x["status"]==200 for x in verified)})
                        if round_id>=5:records+=verified
                        print(json.dumps({"size":size,"round":round_id,"success":rounds[-1]["success"],"max_ms":max(x["latency_ms"] for x in verified)}),flush=True)
                        if not all(x["persisted_correct"] for x in verified):
                            aborted=f"Incorrect restoration size {size} round {round_id}; class stopped to avoid history contamination"
                            break
                    durations=[x["latency_ms"] for x in records if x["status"]==200]
                    metrics={"history_size":size,"measured_requests":len(records),"warmup_requests":min(len(rounds),5)*60,"successful":len(durations),
                        "statuses":{str(s):sum(x["status"]==s for x in records) for s in set(x["status"] for x in records)},
                        "timeouts":sum(x["error"] is not None and "Timeout" in x["error"] for x in records),
                        "errors":sum(x["status"]!=200 for x in records),"correct_restorations_including_warmup":correct,
                        "correctness_failures":len(rounds)*60-correct,"aborted_reason":aborted,
                        "mean_ms":sum(durations)/len(durations) if durations else None,
                        "p50_ms":nearest(durations,.5),"p95_ms":nearest(durations,.95),"p99_ms":nearest(durations,.99),"max_ms":max(durations) if durations else None,
                        "throughput_requests_s":len(records)/sum(x["wall_seconds"] for x in rounds[5:]),
                        "rounds":rounds,"history_json_utf8_bytes":len(json.dumps(prior,ensure_ascii=False).encode())}
                    metrics["target"]="MET" if len(durations)==3000 and metrics["p95_ms"]<=2000 and metrics["errors"]==0 else "NOT MET"
                    report["classes"].append(metrics);resources(api.process.pid);save("results.json",report)
            # Prepare two eligible independent contention fixtures through real Send.
            for kind in ["undo-undo","send-undo"]:
                cid="vt013-contention-"+kind;clusters([cid])
                sent=api.client.post(path(cid)+"/messages",json={"message":TEXT});assert sent.status_code==200
                report["contention"].append({"kind":kind,"cluster":cid,"eligible":sent.json()})
        for item in report["contention"]:
            cid=item["cluster"]
            with patch("subprocess.Popen",side_effect=launch), APIProcess(ns,"concurrent-undo") as api, ThreadPoolExecutor(max_workers=2) as pool:
                def mutate(op):return op,api.client.post(path(cid)+( "/undo" if op=="undo" else "/messages"),json={"expected_revision":item["eligible"]["revision"]} if op=="undo" else {"message":TEXT})
                responses=list(pool.map(mutate,["undo","undo" if item["kind"]=="undo-undo" else "send"]))
                assert sorted(r.status_code for _,r in responses)==[200,409]
                op,winner=next((op,r) for op,r in responses if r.status_code==200)
                expected=[] if op=="undo" else turn(TEXT)+turn(TEXT)
                raw=driver.get(index=ns.index,id=cid)
                assert raw["_source"]["messages"]==expected==winner.json()["messages"]
                assert raw["_source"].get("undo")== (None if op=="undo" else {"messages":turn(TEXT)})
                item.update(winning_operation=op,statuses=[r.status_code for _,r in responses],persisted=raw,correct=True)
        report["completed"] = True
    except Exception as exc:
        report["failure_or_blocker"] = type(exc).__name__+": "+str(exc)
        print(report["failure_or_blocker"],flush=True)
    finally:
        if driver:driver.close()
        if owned:
            info=json.loads(command("cleanup-ownership",["docker","inspect",owned]))[0]
            assert info["Config"]["Labels"]["vt013.performance"]==tag
            command("server-log",["docker","logs",owned]);command("cleanup",["docker","rm","-f",owned]);report["owned_container_removed"]=True
        report["changed_tracked_files"]=[p for p,h in original.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
        report["finished_utc"]=datetime.now(timezone.utc).isoformat();save("results.json",report)
    return 0 if report.get("completed") and not report["changed_tracked_files"] else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:serve()
    else:raise SystemExit(run())
