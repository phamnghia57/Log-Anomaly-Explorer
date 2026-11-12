from importlib import import_module

from fastapi.testclient import TestClient

app = import_module("query-api.src.main").app


def test_cluster_patch_preflight_allows_only_configured_origin():
    client = TestClient(app)
    headers = {"Access-Control-Request-Method": "PATCH",
               "Access-Control-Request-Headers": "Authorization, Content-Type"}
    origin = "http://localhost:5173"
    allowed = client.options("/clusters/c1", headers={**headers, "Origin": origin})
    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == origin
    assert "PATCH" in allowed.headers["Access-Control-Allow-Methods"]

    rejected = client.options("/clusters/c1", headers={**headers, "Origin": "https://foreign.example"})
    assert rejected.status_code == 400
    assert "Access-Control-Allow-Origin" not in rejected.headers
