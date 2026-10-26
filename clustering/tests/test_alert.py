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
