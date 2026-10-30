"""Test config doc lap, khong can OpenSearch, JWT library hay credentials that."""

import runpy
import secrets
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clean_auth_env(monkeypatch):
    for name in (
        "JWT_SECRET", "JWT_EXPIRY_SECONDS", "ADMIN_SEED_USERNAME",
        "ADMIN_SEED_PASSWORD", "USERS_INDEX",
    ):
        monkeypatch.delenv(name, raising=False)


def load_config():
    # Moi lan doc lai env ma khong thay doi module config cua cac test API.
    return runpy.run_path(str(Path(__file__).parents[1] / "src/config.py"))


def test_defaults_do_not_invent_credentials():
    config = load_config()

    assert config["JWT_SECRET"] is None
    assert config["JWT_EXPIRY_SECONDS"] == 3600
    assert config["USERS_INDEX"] == "users"
    assert config["ADMIN_SEED_USERNAME"] is None
    assert config["ADMIN_SEED_PASSWORD"] is None
    with pytest.raises(ValueError, match="^JWT_SECRET must be set for authentication$"):
        config["require_jwt_secret"]()


def test_environment_overrides(monkeypatch):
    secret = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(24)
    values = {
        "JWT_SECRET": secret,
        "JWT_EXPIRY_SECONDS": "7200",
        "ADMIN_SEED_USERNAME": "test-admin",
        "ADMIN_SEED_PASSWORD": password,
        "USERS_INDEX": "test-users",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = load_config()

    assert config["require_jwt_secret"]() == secret
    assert config["JWT_EXPIRY_SECONDS"] == 7200
    assert config["ADMIN_SEED_USERNAME"] == values["ADMIN_SEED_USERNAME"]
    assert config["ADMIN_SEED_PASSWORD"] == password
    assert config["USERS_INDEX"] == "test-users"


@pytest.mark.parametrize("secret", ["", " ", "\t\n"])
def test_empty_secret_is_rejected_for_auth(monkeypatch, secret):
    monkeypatch.setenv("JWT_SECRET", secret)

    with pytest.raises(ValueError, match="^JWT_SECRET must be set for authentication$"):
        load_config()["require_jwt_secret"]()


@pytest.mark.parametrize("expiry", ["0", "-1", "abc", "1.5", "", " "])
def test_invalid_expiry_is_rejected(monkeypatch, expiry):
    monkeypatch.setenv("JWT_EXPIRY_SECONDS", expiry)

    with pytest.raises(ValueError, match="^JWT_EXPIRY_SECONDS must be a positive integer$"):
        load_config()


@pytest.mark.parametrize("index", ["", " "])
def test_empty_users_index_is_rejected(monkeypatch, index):
    monkeypatch.setenv("USERS_INDEX", index)

    with pytest.raises(ValueError, match="^USERS_INDEX must not be empty$"):
        load_config()
