"""
Nhom cac loi tuong tu (clustering).

TODO (Nam): thay the thuat toan placeholder (group theo message nguyen van)
bang mot cach nhom thuc su (vd. chuan hoa message roi hash, hoac dung similarity
tren stack_trace/message qua TF-IDF + clustering).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def _signature(log: dict) -> str:
    """Dac trung dung de nhom. Placeholder: dung nguyen message.

    TODO: chuan hoa (bo so, bo id dong) truoc khi group, de hai loi
    "User 123 not found" va "User 456 not found" duoc nhom chung.
    """
    return log.get("message", "")


def group_similar_errors(logs: Iterable[dict]) -> dict[str, list[dict]]:
    """Nhom danh sach log (chi nhung log level ERROR/FATAL) theo signature.

    Tra ve: { signature: [log, log, ...] }
    Day la dau vao cho anomaly_score.compute_anomaly_score().
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for log in logs:
        if log.get("level") not in ("ERROR", "FATAL"):
            continue
        groups[_signature(log)].append(log)
    return dict(groups)
