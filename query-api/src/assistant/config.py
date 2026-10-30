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
# commit key/endpoint that. Doc lai moi lan goi (khong cache o module-load-
# time) de test monkeypatch bang os.environ duoc thoai mai.
def _azure_openai_api_key() -> str | None:
    return os.environ.get("AZURE_OPENAI_API_KEY")


def azure_openai_endpoint() -> str:
    """Dung Azure OpenAI (khong dung OpenAI truc tiep): VM dang chay o vung
    Azure "East Asia" (Hong Kong) bi OpenAI chan theo IP
    (unsupported_country_region_territory) - xem
    docs/architect/contracts/api-contract.md muc "AI Assistant". Resource
    Azure OpenAI tao o VUNG KHAC (vd. Southeast Asia/East US), khong lien
    quan vung cua VM goi den no."""
    return os.environ.get("AZURE_OPENAI_ENDPOINT", "")


AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
# Ten DEPLOYMENT (dat luc deploy model tren Azure OpenAI), khong phai ten model
# goc - Azure dung ten deployment lam gia tri "model" khi goi chat completions.
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")
# Gioi han thoi gian cho MOI lan goi Azure OpenAI (giay) - model dong reasoning
# (vd. gpt-5-mini) co the suy luan rat lau, can chan tren de khong treo vo thoi
# han; het han thi loi duoc bat o router.py (502), khong treo request mai mai.
AZURE_OPENAI_TIMEOUT_SECONDS = _positive_int("AZURE_OPENAI_TIMEOUT_SECONDS", 60)
# Muc do "suy nghi" cua model dong reasoning (minimal/low/medium/high - xem
# Azure OpenAI reasoning models doc). prj2 chi can cau tra loi nhanh, chat
# luong trung binh la du (du lieu la log demo tu sinh) - de "low" thay vi mac
# dinh cua Azure (thuong la "medium"/"high") de giam do tre dang ke.
ASSISTANT_REASONING_EFFORT = os.environ.get("ASSISTANT_REASONING_EFFORT", "low")
CONVERSATIONS_INDEX = os.environ.get("ASSISTANT_CONVERSATIONS_INDEX", "assistant-conversations")
# Gioi han so vong AI tu goi tool trong 1 luot chat - bao ve chi phi/do tre va
# tranh vong lap tool-calling khong diem dung. De THAP (khong phai 5): du lieu
# prj2 la log TU SINH/MO PHONG trong demo, AI chi can neu nguyen nhan co ban
# tu sample log da co san trong system prompt, khong can dieu tra nhieu vong -
# giam ca do tre va chi phi (dac biet voi model dong reasoning nhu gpt-5-mini).
MAX_TOOL_ROUNDS = _positive_int("ASSISTANT_MAX_TOOL_ROUNDS", 2)
MAX_OUTPUT_TOKENS = _positive_int("ASSISTANT_MAX_OUTPUT_TOKENS", 1200)
# Chi dung de HIEN THI trong system prompt cho AI biet nguong dang ap dung,
# khong doc truc tiep tu clustering (khac process, khac bien moi truong).
ANOMALY_THRESHOLD_HINT = os.environ.get("ANOMALY_THRESHOLD", "2.0")


def require_azure_openai_api_key() -> str:
    """Tu choi assistant neu thieu key/endpoint; KHONG anh huong cac route khac cua query-api."""
    key = _azure_openai_api_key()
    if key is None or not key.strip():
        raise ValueError("AZURE_OPENAI_API_KEY must be set to use the AI Assistant")
    if not azure_openai_endpoint().strip():
        raise ValueError("AZURE_OPENAI_ENDPOINT must be set to use the AI Assistant")
    return key
