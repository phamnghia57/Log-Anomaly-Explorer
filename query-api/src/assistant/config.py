"""Cau hinh AI Assistant, doc tu bien moi truong, tach khoi cau hinh ingestion
va cau hinh auth (query-api/src/config.py, chua len main - xem auth-deployment).
"""

from __future__ import annotations

import os


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive integer") from None
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


# Khong co default: nguoi dung tu dien vao .env (xem .env.example), khong
# commit key that. Doc lai moi lan goi require_openai_api_key() (khong cache
# o module-load-time) de test monkeypatch duoc thoai mai.
def _openai_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY")


OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
CONVERSATIONS_INDEX = os.environ.get("ASSISTANT_CONVERSATIONS_INDEX", "assistant-conversations")
# Gioi han so vong AI tu goi tool trong 1 luot chat - bao ve chi phi OpenAI va
# do tre, tranh vong lap tool-calling khong diem dung.
MAX_TOOL_ROUNDS = _positive_int("ASSISTANT_MAX_TOOL_ROUNDS", 5)
MAX_OUTPUT_TOKENS = _positive_int("ASSISTANT_MAX_OUTPUT_TOKENS", 1200)
# Chi dung de HIEN THI trong system prompt cho AI biet nguong dang ap dung,
# khong doc truc tiep tu clustering (khac process, khac bien moi truong).
ANOMALY_THRESHOLD_HINT = os.environ.get("ANOMALY_THRESHOLD", "2.0")


def require_openai_api_key() -> str:
    """Tu choi assistant neu thieu key; KHONG anh huong cac route khac cua query-api."""
    key = _openai_api_key()
    if key is None or not key.strip():
        raise ValueError("OPENAI_API_KEY must be set to use the AI Assistant")
    return key
