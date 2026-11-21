"""Chay that run_worker_storm.sh voi `docker`/`curl` gia tren PATH (#103).

Kiem 2 loi review PR #127:
  - xoa storm-* khong duoc nuot loi: phai xoa theo TUNG TEN (chiu duoc
    action.destructive_requires_name) va kiem lai _cat/indices, con sot -> exit 1;
  - restore phai nhac resume Healthchecks + UptimeRobot va bao khi alert/ping
    van tat.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "load-tests" / "run_worker_storm.sh"

FAKE_DOCKER = r'''#!/usr/bin/env bash
# docker gia: chi hieu cac lenh run_worker_storm.sh dung trong `restore`.
state="$FAKE_STATE"
echo "docker $*" >> "$state/calls"
[ "$1" = compose ] || exit 0
shift
case "$1" in
  exec)
    shift; [ "$1" = -T ] && shift
    svc="$1"; shift
    if [ "$1" = printenv ]; then
      f="$state/env-$svc-$2"; [ -f "$f" ] && cat "$f"; exit 0
    fi
    if [ "$svc" = opensearch ] && [ "$1" = curl ]; then
      shift; method=GET
      for a in "$@"; do case "$a" in -XDELETE) method=DELETE;; localhost:9200/*) url="${a#localhost:9200/}";; esac; done
      if [ "$method" = DELETE ]; then
        case "$url" in *'*'*)
          echo '{"error":{"type":"illegal_argument_exception","reason":"Wildcard expressions or all indices are not allowed"},"status":400}'
          exit 0;;
        esac
        if [ -n "${FAKE_REFUSE:-}" ]; then echo '{"error":"forbidden","status":403}'; exit 0; fi
        grep -vx "$url" "$state/indices" > "$state/indices.new" || true
        mv "$state/indices.new" "$state/indices"
        echo '{"acknowledged":true}'
        exit 0
      fi
      case "$url" in _cat/indices/storm-*) cat "$state/indices";; esac
      exit 0
    fi
    exit 0;;
  *) exit 0;;
esac
'''

FAKE_CURL = "#!/usr/bin/env bash\nexit 0\n"


@pytest.fixture
def fake_env(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("can bash")
    bin_dir = tmp_path / "bin"
    state = tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        path = bin_dir / name
        path.write_text(body, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    (state / "indices").write_text("storm-logs\nstorm-clusters\nstorm-cluster-history\n")
    (state / "env-clustering-CLUSTER_INDEX").write_text("clusters\n")
    (state / "env-ingestion-LOG_INDEX").write_text("logs\n")
    # Ban sao script trong repo gia (script tu cd ve goc repo va doc .env o do).
    repo = tmp_path / "repo"
    (repo / "load-tests").mkdir(parents=True)
    (repo / "docker-compose.yml").write_text("services: {}\n")
    shutil.copy(SCRIPT, repo / "load-tests" / SCRIPT.name)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_STATE": str(state),
           "STORM_MARKER": str(tmp_path / "marker"), "YES": "1", "INGESTION_HOST": "http://fake:9000",
           "FAKE_REPO": str(repo)}
    (tmp_path / "marker").write_text("2026-11-21T03:00:00Z\n")
    return env, state, tmp_path


def _run(env, *args, stdin=None):
    script = Path(env["FAKE_REPO"]) / "load-tests" / SCRIPT.name
    return subprocess.run(["bash", str(script), *args], env=env, input=stdin,
                          capture_output=True, text=True, timeout=60)


def test_script_la_lf_va_khong_con_wildcard_delete_nuot_loi():
    text = SCRIPT.read_bytes()
    assert b"\r\n" not in text
    assert b"storm-*?expand_wildcards=all' >/dev/null || true" not in text
    assert b"-XDELETE 'localhost:9200/storm-*" not in text


def test_restore_xoa_tung_index_theo_ten_va_nhac_resume_monitor(fake_env):
    env, state, tmp = fake_env
    result = _run(env, "restore")
    assert result.returncode == 0, result.stderr
    assert (state / "indices").read_text().strip() == ""
    calls = (state / "calls").read_text()
    for name in ("storm-logs", "storm-clusters", "storm-cluster-history"):
        assert f"localhost:9200/{name}" in calls
    assert "storm-*?expand" not in calls.replace("_cat/indices/storm-*?h=index&expand", "")
    assert "_cat/indices/storm-*: rong" in result.stdout
    assert "Healthchecks" in result.stderr and "UptimeRobot" in result.stderr
    assert "2026-11-21T03:00:00Z" in result.stdout  # nhac da tat giam sat tu luc nao
    assert not (tmp / "marker").exists()


def test_restore_dung_lai_khi_opensearch_tu_choi_xoa(fake_env):
    env, state, _ = fake_env
    result = _run({**env, "FAKE_REFUSE": "1"}, "restore")
    assert result.returncode != 0
    assert "tu choi xoa storm-logs" in result.stderr
    assert "storm-logs" in (state / "indices").read_text()


def test_restore_bao_khi_alert_va_ping_van_tat(fake_env):
    env, _, _ = fake_env
    (Path(env["FAKE_REPO"]) / ".env").write_text(
        "ALERT_WEBHOOK_URL=https://hook.example/x\nHEALTHCHECK_PING_URL=https://hc.example/y\n")
    result = _run(env, "restore")
    assert result.returncode != 0
    assert "ALERT_WEBHOOK_URL nhung clustering dang de TRONG" in result.stderr
    assert "HEALTHCHECK_PING_URL nhung clustering dang de TRONG" in result.stderr


def test_restore_khong_yes_bat_go_resumed(fake_env):
    env, _, tmp = fake_env
    env = {k: v for k, v in env.items() if k != "YES"}
    result = _run(env, "restore", stdin="y\n")
    assert result.returncode != 0  # "y" khong du, het stdin -> bao chua resume
    assert "CHUA xac nhan resume monitor" in result.stderr
    assert (tmp / "marker").exists()  # marker con -> lan restore sau van nhac
    ok = _run(env, "restore", stdin="resumed\n")
    assert ok.returncode == 0, ok.stderr
    assert not (tmp / "marker").exists()
