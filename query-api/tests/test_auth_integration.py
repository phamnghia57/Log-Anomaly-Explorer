"""Seed -> login -> all protected routes with one shared mocked OpenSearch client."""

import importlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi.testclient import TestClient
from jsonschema import FormatChecker, validate

auth_stack = importlib.import_module("query-api.tests.auth_stack").auth_stack


def test_seed_login_query_and_expiration_preserve_contracts(caplog):
    seed = importlib.import_module("query-api.src.seed_admin")
    passwords = importlib.import_module("query-api.src.passwords")
    with auth_stack() as stack:
        assert seed.seed_admin(stack.repository) is True
        saved = deepcopy(stack.documents["auth-test-users", stack.credentials["username"]])
        assert seed.seed_admin(stack.repository) is False
        assert stack.documents["auth-test-users", stack.credentials["username"]] == saved
        contracts = Path(__file__).resolve().parents[2] / "docs/architect/contracts"
        validate(saved, json.loads((contracts / "users-schema.json").read_text()), format_checker=FormatChecker())
        assert passwords.verify_password(stack.credentials["password"], saved["password_hash"])
        assert stack.credentials["password"] not in json.dumps(list(stack.documents.values()))
        assert stack.client.create.call_count == 1

        with TestClient(stack.app) as client:
            login = client.post("/auth/login", json=stack.credentials)
            assert login.status_code == 200
            assert set(login.json()) == {"token", "expires_at"}
            token = login.json()["token"]
            claims = jwt.decode(token, stack.secret, algorithms=["HS256"], options={"require": ["sub", "role", "exp"]})
            assert claims["sub"] == stack.credentials["username"]
            assert claims["role"] == "admin"
            assert claims["exp"] == int(datetime.fromisoformat(login.json()["expires_at"]).timestamp())
            valid = {"Authorization": f"Bearer {token}"}
            expired = jwt.encode({**claims, "exp": int((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp())},
                                 stack.secret, algorithm="HS256")
            paths = ["/search", "/clusters", "/clusters/auth-test-cluster", "/clusters/auth-test-cluster/history"]
            for path in paths:
                reads = stack.client.search.call_count + stack.client.get.call_count
                for headers in ({}, {"Authorization": "Bearer invalid"}, {"Authorization": f"Bearer {expired}"}):
                    assert client.get(path, headers=headers).status_code == 401
                assert stack.client.search.call_count + stack.client.get.call_count == reads
                assert client.get(path, headers=valid).status_code == 200

            search = client.get("/search", headers=valid).json()
            assert search == {"total": 1, "results": [{**stack.log, "log_id": "auth-test-log"}]}
            validate(stack.log, json.loads((contracts / "log-schema.json").read_text()), format_checker=FormatChecker())
            validate(stack.cluster, json.loads((contracts / "cluster-record.schema.json").read_text()), format_checker=FormatChecker())
            assert client.get("/clusters", headers=valid).json() == {"total": 1, "clusters": [stack.cluster]}
            assert client.get("/clusters/auth-test-cluster", headers=valid).json() == {
                **stack.cluster, "logs": search["results"], "logs_total": 1,
            }
            assert client.get("/clusters/auth-test-cluster/history", headers=valid).json() == {
                "cluster_id": "auth-test-cluster", "points": [stack.point],
            }
            assert client.get("/health").status_code == 200
            for path in ("/auth/register", "/auth/signup", "/auth/reset-password"):
                assert client.post(path, json=stack.credentials).status_code == 404
        assert stack.credentials["password"] not in caplog.text
        assert stack.secret not in caplog.text
