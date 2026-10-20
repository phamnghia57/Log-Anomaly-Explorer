"""
Nhom cac loi tuong tu (clustering).

TODO (Nam): thay the thuat toan placeholder (group theo message nguyen van)
bang mot cach nhom thuc su (vd. chuan hoa message roi hash, hoac dung similarity
tren stack_trace/message qua TF-IDF + clustering).
"""

from __future__ import annotations
import hashlib
import re
from collections import defaultdict
from typing import Iterable

# Thu tu quan trong: pattern cu the (uuid, email, ip, hex) dung truoc so thuan.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<UUID>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<EMAIL>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<IP>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<HEX>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<HEX>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<NUM>"),
]

_LEVELS = ("ERROR", "FATAL")

# Khoa cua mot cum: (service, signature)
ClusterKey = tuple[str, str]

def normalize_message(message: str) -> str:
    """Bien message thanh template: bo gia tri dong, giu phan co dinh."""
    text = (message or "").strip()
    for pattern, placeholder in _PATTERNS:
        text = pattern.sub(placeholder, text)
    return re.sub(r"\s+", " ", text)


def _signature(log: dict) -> str:
    """Dac trung dung de nhom. Placeholder: dung nguyen message.

    TODO: chuan hoa (bo so, bo id dong) truoc khi group, de hai loi
    "User 123 not found" va "User 456 not found" duoc nhom chung.
    """
    return normalize_message(log.get("message", ""))

def _service(log: dict) -> str:
    return log.get("service") or "unknown"

def make_cluster_id(service: str, signature: str) -> str:
    """ID on dinh cho mot cum: cung (service, signature) -> cung ID o moi lan chay.

    Can on dinh de link Incident View (/clusters/{id}) cua Nghia khong bi vo
    khi job chay lai. Luu y: neu sua _PATTERNS thi signature doi -> ID doi.
    """
    raw = f"{service}|{signature}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]



def group_similar_errors(logs: Iterable[dict]) -> dict[ClusterKey, list[dict]]:
    """Nhom danh sach log (chi nhung log level ERROR/FATAL) theo signature.

    Tra ve: { signature: [log, log, ...] }
    Day la dau vao cho anomaly_score.compute_anomaly_score().
    """
    groups: dict[ClusterKey, list[dict]] = defaultdict(list)
    for log in logs:
        if log.get("level") not in _LEVELS:
            continue
        groups[(_service(log), _signature(log))].append(log)
    return dict(groups)

if __name__ == "__main__":
    sample = [
        {"level": "ERROR", "service": "demo-web", "message": "User 123 not found"},
        {"level": "ERROR", "service": "demo-web", "message": "User 456 not found"},
        {"level": "ERROR", "service": "demo-mobile-api", "message": "User 123 not found"},
        {"level": "FATAL", "service": "demo-web", "message": "Timeout calling payment after 3021 ms for order 8841"},
        {"level": "ERROR", "service": "demo-web", "message": "Timeout calling payment after 187 ms for order 1203"},
        {"level": "INFO", "service": "demo-web", "message": "User 789 logged in"},
    ]
    for (service, sig), items in group_similar_errors(sample).items():
        print(len(items), "|", service, "|", sig, "|", make_cluster_id(service, sig))
