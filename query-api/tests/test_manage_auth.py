import importlib
from unittest.mock import Mock
import pytest
from ingestion.src.storage import StorageError

manage = importlib.import_module("query-api.src.manage_auth")


def test_cli_init_migrates_auth_indexes(monkeypatch):
    users, sessions, limits = Mock(), Mock(), Mock()
    monkeypatch.setattr(manage, "UserRepository", lambda: users)
    monkeypatch.setattr(manage, "SessionRepository", lambda store: sessions)
    monkeypatch.setattr(manage, "LoginLimiter", lambda store: limits)
    assert manage.main(["init"]) == 0
    users.ensure_ready.assert_called_once()
    sessions.ensure_ready.assert_called_once()
    limits.ensure_ready.assert_called_once()
    users.close.assert_called_once()


@pytest.mark.parametrize("action", ["disable", "enable", "revoke-all"])
def test_cli_account_actions(monkeypatch, action):
    users = Mock()
    monkeypatch.setattr(manage, "UserRepository", lambda: users)
    assert manage.main([action, "test-admin"]) == 0
    users.administer.assert_called_once_with("test-admin", action, value=None)


def test_password_is_prompted_twice_never_printed(monkeypatch, capsys):
    users = Mock()
    monkeypatch.setattr(manage, "UserRepository", lambda: users)
    monkeypatch.setattr(manage.getpass, "getpass", Mock(side_effect=["test-secret", "test-secret"]))
    assert manage.main(["set-password", "test-admin"]) == 0
    users.administer.assert_called_once_with("test-admin", "set-password", value="test-secret")
    output = capsys.readouterr()
    assert "test-secret" not in output.out + output.err


def test_password_mismatch_and_storage_failure_are_sanitized(monkeypatch, capsys):
    users = Mock()
    monkeypatch.setattr(manage, "UserRepository", lambda: users)
    monkeypatch.setattr(manage.getpass, "getpass", Mock(side_effect=["one-secret", "another-secret"]))
    assert manage.main(["set-password", "test-admin"]) == 1
    users.administer.assert_not_called()
    users.administer.side_effect = StorageError("private connection details")
    assert manage.main(["disable", "test-admin"]) == 1
    output = capsys.readouterr()
    for value in ("one-secret", "another-secret", "private connection details"):
        assert value not in output.out + output.err
