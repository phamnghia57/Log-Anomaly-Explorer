"""Test payload alert - dac biet field `trace_id` dung ghep link Jaeger
(xem docs/architect/contracts/api-contract.md muc "Alert").
"""
import httpx
import pytest

from clustering.src import alert


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://webhook.test/hook")
    monkeypatch.setenv("ANOMALY_THRESHOLD", "2.0")
    alert.reset_alert_state()
    yield
    alert.reset_alert_state()


@pytest.fixture()
def sent(monkeypatch):
    """Bat payload gui di, tra ve 200 nhu webhook that chap nhan."""
    captured = []

    def fake_post(url, json, timeout):
        captured.append({"url": url, "json": json})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(alert.httpx, "post", fake_post)
    return captured


def record(**over):
    base = {"cluster_id": "c1", "score": 5.0, "first_seen": "2026-10-26T00:00:00+00:00",
            "trace_ids": ["aaa", "bbb"], "status": "normal"}
    base.update(over)
    return base


def test_payload_co_trace_id_dai_dien(sent):
    assert alert.check_and_alert(record(), "demo-web") is True

    payload = sent[0]["json"]
    assert payload["trace_id"] == "aaa"  # phan tu dau trong trace_ids
    assert payload["cluster_id"] == "c1"
    assert payload["service"] == "demo-web"


def test_trace_id_la_null_khi_cum_khong_co_trace(sent):
    """Key luon ton tai de template ben nhan khong vo - chi gia tri la null."""
    assert alert.check_and_alert(record(trace_ids=[]), "demo-web") is True

    payload = sent[0]["json"]
    assert "trace_id" in payload
    assert payload["trace_id"] is None


def test_khong_co_key_trace_ids_van_gui_duoc(sent):
    """ClusterRecord cu (ghi truoc khi co field nay) khong duoc lam vo alert."""
    cluster = record()
    del cluster["trace_ids"]

    assert alert.check_and_alert(cluster, "demo-web") is True
    assert sent[0]["json"]["trace_id"] is None


def test_duoi_nguong_thi_khong_gui(sent):
    assert alert.check_and_alert(record(score=1.0), "demo-web") is False
    assert sent == []


def test_batch_sends_one_digest_and_preserves_cooldown(sent):
    first, second, normal = record(), record(cluster_id="c2"), record(cluster_id="c3", score=1)
    records = [("web", first), ("api", second), ("web", normal)]
    assert alert.check_and_alert_batch(records, window_to="2026-10-26T00:01:00Z") == 2
    assert len(sent) == 1
    payload = sent[0]["json"]
    assert payload["count"] == 2
    assert [a["service"] for a in payload["alerts"]] == ["web", "api"]
    assert "c1" in payload["message"] and "c2" in payload["message"]
    assert payload["window_to"] == "2026-10-26T00:01:00Z"
    assert [c["status"] for _, c in records] == ["alerted", "alerted", "normal"]
    assert alert.check_and_alert_batch(records) == 0
    assert len(sent) == 1


def test_failed_batch_retries_all_clusters(monkeypatch, sent):
    post = alert.httpx.post
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(alert.httpx, "post", fail)
    records = [("web", record()), ("api", record(cluster_id="c2"))]
    assert alert.check_and_alert_batch(records) == 0
    assert all(c["status"] == "anomalous" for _, c in records)
    monkeypatch.setattr(alert.httpx, "post", post)
    assert alert.check_and_alert_batch(records) == 2
    assert len(sent) == 1


def test_missing_webhook_does_not_start_cooldown(monkeypatch, sent):
    records = [("web", record())]
    monkeypatch.delenv("ALERT_WEBHOOK_URL")
    assert alert.check_and_alert_batch(records) == 0
    assert records[0][1]["status"] == "anomalous"
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://webhook.test/hook")
    assert alert.check_and_alert_batch(records) == 1


class CooldownStore:
    def __init__(self, data):
        self.data = data

    def get_alert_times(self, ids):
        return {key: self.data[key] for key in ids if key in self.data}

    def write_alert_times(self, ids, sent_at):
        self.data.update(dict.fromkeys(ids, sent_at))


def test_persistent_cooldown_survives_restart_and_expires(monkeypatch, sent):
    data = {}
    monkeypatch.setenv("ALERT_COOLDOWN_SECONDS", "600")
    monkeypatch.setattr(alert.time, "time", lambda: 1000)
    assert alert.check_and_alert(record(), store=CooldownStore(data))
    assert data == {"c1": 1000}
    alert.reset_alert_state()
    monkeypatch.setattr(alert.time, "time", lambda: 1599)
    assert not alert.check_and_alert(record(), store=CooldownStore(data))
    monkeypatch.setattr(alert.time, "time", lambda: 1600)
    assert alert.check_and_alert(record(), store=CooldownStore(data))
    assert len(sent) == 2


def test_persistent_failed_delivery_does_not_start_cooldown(monkeypatch, sent):
    data = {}
    post = alert.httpx.post
    monkeypatch.setattr(alert.httpx, "post", lambda *a, **kw: httpx.Response(
        500, request=httpx.Request("POST", "http://webhook.test")))
    assert not alert.check_and_alert(record(), store=CooldownStore(data))
    assert data == {}
    monkeypatch.setattr(alert.httpx, "post", post)
    assert alert.check_and_alert(record(), store=CooldownStore(data))


def test_cooldown_read_failure_prevents_delivery(sent):
    class Broken(CooldownStore):
        def get_alert_times(self, ids):
            raise RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        alert.check_and_alert(record(), store=Broken({}))
    assert sent == []


def test_persistence_failure_is_reported(sent):
    class Broken(CooldownStore):
        def write_alert_times(self, ids, sent_at):
            raise RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        alert.check_and_alert(record(), store=Broken({}))
    assert len(sent) == 1


@pytest.mark.parametrize("value", ["", "oops", "-1", "nan", "inf"])
def test_invalid_cooldown_environment_uses_default(monkeypatch, value):
    monkeypatch.setenv("ALERT_COOLDOWN_SECONDS", value)
    assert alert._float_env("ALERT_COOLDOWN_SECONDS", 600) == 600
