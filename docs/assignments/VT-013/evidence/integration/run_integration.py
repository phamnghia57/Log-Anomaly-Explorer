"""Own a disposable OpenSearch 2.17.1, capture real HTTP tests, and remove only it.

Run from an existing Python environment containing requirements-dev.txt.
Docker must already be running. No compose, shared volumes, index deletion,
host dependency installation, production code edits, or project .env loading.
"""

from datetime import datetime, timezone
import hashlib
from importlib import metadata, util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
IMAGE = "opensearchproject/opensearch:2.17.1"
INTEGRATION = "tests/test_assistant_undo_integration.py"
REGRESSION = ["tests/test_assistant_undo_contract.py", "tests/test_assistant_undo_backend.py",
              "tests/test_assistant.py", "tests/test_assistant_storage.py"]
PROTECTED = ["query-api/src/assistant/storage.py", "query-api/src/assistant/router.py",
             "query-api/Dockerfile", "docs/architect/contracts/assistant-conversation-schema.json",
             "docs/architect/contracts/api-contract.md", "docs/assignments/VT-013/plan.md"]
TEST_SOURCES = ["query-api/tests/test_assistant_undo_integration.py",
                "query-api/tests/vt013_integration_server.py",
                "docs/assignments/VT-013/evidence/integration/run_integration.py"]
spec = util.spec_from_file_location("vt013_capture", HERE.parent / "red/run_red.py")
capture = util.module_from_spec(spec)
spec.loader.exec_module(capture)
capture.HERE = HERE


def command(name, argv, *, timeout=120, cwd=ROOT):
    print(f"Running {name}", flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=timeout)
        output, code, timed_out = result.stdout, result.returncode, False
    except subprocess.TimeoutExpired as error:
        output, code, timed_out = error.stdout or b"", None, True
    info = {"command": argv, "cwd": str(cwd), "exit_code": code, "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - started, 3)}
    text = "\n".join(line.rstrip() for line in output.decode("utf-8", errors="replace").splitlines()) + "\n"
    (HERE / f"{name}.log").write_text(json.dumps(info, indent=2) + "\n\n" + text,
                                    encoding="utf-8", newline="\n")
    return info, text


def require(name, argv, *, timeout=120):
    info, output = command(name, argv, timeout=timeout)
    report["commands"].append(info)
    if info["exit_code"] != 0:
        raise RuntimeError(f"{name}: exit={info['exit_code']}, timeout={info['timed_out']}; see {name}.log")
    return output.strip()


def hashes():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PROTECTED}


report = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
          "interpreter": sys.executable, "packages": {p: metadata.version(p) for p in (
              "pytest", "fastapi", "starlette", "httpx", "pydantic", "opensearch-py", "jsonschema")},
          "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
          "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
          "production_sha256_before": hashes(), "commands": [], "runs": [],
          "test_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in TEST_SOURCES},
          "real_integration": "NOT VERIFIED", "docker_build": "NOT VERIFIED", "python311": "NOT VERIFIED"}


def main():
    run_id = uuid4().hex[:16]
    name = f"vt013-integration-{run_id}"
    container_id = None
    try:
        require("docker-version", ["docker", "version", "--format", "{{json .}}"], timeout=30)
        require("opensearch-image", ["docker", "image", "inspect", IMAGE,
                                   "--format", "{{json .}}"], timeout=30)
        container_id = require("opensearch-start", [
            "docker", "run", "-d", "--name", name, "--label", f"vt013.run={run_id}",
            "--publish", "127.0.0.1::9200", "--memory", "2g",
            "--ulimit", "nofile=65536:65536", "--tmpfs",
            "/usr/share/opensearch/data:rw,uid=1000,gid=1000,size=1g",
            "--env", "discovery.type=single-node", "--env", f"cluster.name={name}",
            "--env", "DISABLE_SECURITY_PLUGIN=true", "--env", "DISABLE_INSTALL_DEMO_CONFIG=true",
            "--env", "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m", IMAGE,
        ], timeout=90)
        owned = json.loads(require("opensearch-inspect", ["docker", "inspect", container_id]))[0]
        assert owned["Config"]["Labels"]["vt013.run"] == run_id
        assert owned["Name"] == "/" + name and not owned["HostConfig"]["Binds"]
        port = owned["NetworkSettings"]["Ports"]["9200/tcp"][0]
        assert port["HostIp"] == "127.0.0.1"
        url = f"http://127.0.0.1:{port['HostPort']}"
        context = {"run_id": run_id, "cluster_name": name, "container_id": container_id, "url": url}
        (HERE / "instance.json").write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        deadline = time.monotonic() + 120
        with httpx.Client(trust_env=False, timeout=2) as client:
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
                raise RuntimeError("Owned OpenSearch did not become ready within 120 seconds")
        os.environ["VT013_INTEGRATION_CONTEXT"] = str(HERE / "instance.json")
        os.environ["VT013_INTEGRATION_ARTIFACTS"] = str(HERE / "host-artifacts")
        print("Running real OpenSearch integration HTTP contracts", flush=True)
        real = capture.run("real-opensearch", [INTEGRATION], timeout=600)
        report["runs"].append(real)
        report["real_integration"] = "PASS" if (real["exit_code"] == 0 and len(real.get("cases", [])) == 13
                                                and all(c["status"] == "passed" for c in real["cases"])) else "FAIL"
        print(json.dumps({"run": "real-opensearch", "exit_code": real["exit_code"],
                          "cases": [{"name": c["name"], "status": c["status"]} for c in real.get("cases", [])]}), flush=True)
        if report["real_integration"] != "PASS":
            raise RuntimeError("Integration assertions/setup failed; preserve logs and investigate before Docker build")

        tag = f"vt013-query-api:{run_id}"
        require("query-api-build", ["docker", "build", "--progress", "plain", "-f", "query-api/Dockerfile",
                                    "-t", tag, "."], timeout=600)
        report["docker_build"] = "PASS"
        require("query-api-image", ["docker", "image", "inspect", tag, "--format", "{{json .}}"])
        probe = (
            "from pathlib import Path; from importlib import import_module,metadata; import json,sys; "
            "m=import_module('query-api.src.assistant.storage'); "
            "assert m._SCHEMA.is_file(); assert sys.version_info[:2]==(3,11); "
            "print(json.dumps({'python':sys.version,'schema':str(m._SCHEMA),"
            "'schema_exists':m._SCHEMA.is_file(),'packages':{p:metadata.version(p) for p in "
            "['fastapi','opensearch-py','jsonschema','uvicorn','pydantic']}}))"
        )
        require("runtime-schema", ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python",
                                   tag, "-B", "-c", probe])
        dockerfile = HERE / "Dockerfile.verify"
        dockerfile.write_text(
            f"FROM {tag}\nUSER root\nRUN python -m pip install --no-cache-dir 'pytest>=8'\nUSER appuser\n",
            encoding="utf-8", newline="\n")
        test_tag = f"vt013-query-api-tests:{run_id}"
        require("python311-test-image-build", ["docker", "build", "--progress", "plain", "-f", str(dockerfile),
                                               "-t", test_tag, "."], timeout=240)
        container_context = dict(context, url="http://127.0.0.1:9200")
        (HERE / "instance-python311.json").write_text(json.dumps(container_context, indent=2) + "\n",
                                                     encoding="utf-8")
        code, _ = command("python311-tests", [
            "docker", "run", "--rm", "--network", f"container:{container_id}",
            "--mount", f"type=bind,src={ROOT / 'query-api/tests'},dst=/app/query-api/tests,readonly",
            "--mount", f"type=bind,src={HERE},dst=/evidence", "--workdir", "/app/query-api",
            "--env", "STORAGE_BACKEND=memory", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "--env", "OTEL_EXPORTER_OTLP_ENDPOINT=",
            "--env", "LANGFUSE_TRACING_ENABLED=false",
            "--env", "VT013_INTEGRATION_CONTEXT=/evidence/instance-python311.json",
            "--env", "VT013_INTEGRATION_ARTIFACTS=/evidence/python311-artifacts",
            "--entrypoint", "python", test_tag, "-u", "-B", "-m", "pytest", "-vv", "--tb=short",
            "-rA", "--color=no", "-p", "no:cacheprovider", "--junitxml=/evidence/python311-tests.junit.xml",
            INTEGRATION, *REGRESSION,
        ], timeout=600)
        report["commands"].append(code)
        report["python311"] = "PASS" if code["exit_code"] == 0 else "FAIL"
    except Exception as error:
        report["blocker_or_failure"] = f"{type(error).__name__}: {error}"
        print(report["blocker_or_failure"], flush=True)
    finally:
        print("Running existing backend regressions without changing their assertions", flush=True)
        regression = capture.run("backend-regression", REGRESSION, timeout=180)
        report["runs"].append(regression)
        print(json.dumps({"run": "backend-regression", "exit_code": regression["exit_code"],
                          "cases": len(regression.get("cases", []))}), flush=True)
        if container_id:
            try:
                logs, _ = command("opensearch-server", ["docker", "logs", container_id])
                report["commands"].append(logs)
                inspect = json.loads(require("cleanup-ownership", ["docker", "inspect", container_id]))[0]
                assert inspect["Config"]["Labels"]["vt013.run"] == run_id
                require("opensearch-cleanup", ["docker", "rm", "-f", container_id])
                report["owned_container_removed"] = True
            except Exception as error:
                report["cleanup_error"] = str(error)
        report["production_sha256_after"] = hashes()
        assert report["production_sha256_before"] == report["production_sha256_after"]
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (HERE / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8", newline="\n")
    return 0 if (report["real_integration"] == "PASS" and report["python311"] == "PASS"
                 and regression["exit_code"] == 0 and "cleanup_error" not in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
