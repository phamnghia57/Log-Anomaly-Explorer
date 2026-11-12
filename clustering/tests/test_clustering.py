import pytest

from clustering.src.clustering import normalize_message, group_similar_errors, make_cluster_id


@pytest.mark.parametrize("message,expected", [
    ("  User 123\n FAILED  ", "user <NUM> failed"),
    ("id 550e8400-e29b-41d4-a716-446655440000", "id <UUID>"),
    ("mail A.Test+tag@example.com", "mail <EMAIL>"),
    ("host 192.168.1.1:8080", "host <IP>"),
    ("code 0xDEAD deadbeef01234567", "code <HEX> <HEX>"),
    (None, ""), ("", ""),
])
def test_normalization(message, expected):
    assert normalize_message(message) == expected


def test_grouping_filters_levels_and_isolates_services():
    logs = [dict(level=level, service=service, message=f"user {i}")
            for i, (level, service) in enumerate([
                ("ERROR", "web"), ("FATAL", "web"), ("ERROR", "api"), ("INFO", "web")])]
    logs.append(dict(level="ERROR", message="user 99"))
    groups = group_similar_errors(iter(logs))
    assert groups == {("web", "user <NUM>"): logs[:2],
                      ("api", "user <NUM>"): [logs[2]],
                      ("unknown", "user <NUM>"): [logs[4]]}
    assert group_similar_errors([]) == {}


def test_cluster_ids_are_stable_and_service_specific():
    assert make_cluster_id("web", "timeout") == make_cluster_id("web", "timeout")
    assert len(make_cluster_id("web", "timeout")) == 16
    assert make_cluster_id("web", "timeout") != make_cluster_id("api", "timeout")
    assert make_cluster_id("web", "timeout") != make_cluster_id("web", "failure")
