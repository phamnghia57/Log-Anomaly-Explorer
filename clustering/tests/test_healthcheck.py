import httpx
import pytest

from clustering.src import healthcheck


def test_disabled_is_silent(monkeypatch, caplog):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", "  ")
    monkeypatch.setattr(healthcheck.httpx, "get", lambda *a, **kw: pytest.fail("unexpected request"))
    healthcheck.ping()
    healthcheck.ping(failed=True)
    assert not caplog.records


@pytest.mark.parametrize("failed,expected", [(False, "https://hc.example/token/?x=1"),
                                            (True, "https://hc.example/token/fail?x=1")])
def test_ping_url_and_timeout(monkeypatch, failed, expected):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", "https://hc.example/token/?x=1")
    calls = []
    def get(url, timeout):
        calls.append((url, timeout))
        return httpx.Response(200, request=httpx.Request("GET", url))
    monkeypatch.setattr(healthcheck.httpx, "get", get)
    healthcheck.ping(failed=failed)
    assert calls == [(expected, 2.0)]


@pytest.mark.parametrize("error", [httpx.ConnectError("secret-token"), ValueError("secret-token")])
def test_ping_failure_does_not_raise_or_expose_token(monkeypatch, caplog, error):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", "https://hc.example/secret-token")
    def get(*args, **kwargs):
        raise error
    monkeypatch.setattr(healthcheck.httpx, "get", get)
    healthcheck.ping()
    assert "Healthcheck signal failed" in caplog.text
    assert "secret-token" not in caplog.text


def test_non_2xx_is_caught(monkeypatch, caplog):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", "https://hc.example/token")
    monkeypatch.setattr(healthcheck.httpx, "get", lambda url, timeout: httpx.Response(
        500, request=httpx.Request("GET", url)))
    healthcheck.ping()
    assert "Healthcheck signal failed" in caplog.text
