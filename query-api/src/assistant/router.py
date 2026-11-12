"""Endpoint AI Assistant - dieu tra & de xuat cach sua cho 1 cum, giong vai
tro cua Elastic Observability AI Assistant nhung thu gon cho du an nay (xem
README.md muc "AI Assistant"). JWT admin duoc gan cho ca router khi include
trong main.py, vi day la du lieu log/stack trace noi bo va goi API OpenAI co phi.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ingestion.src.storage import StorageError

from . import config
from .service import last_call_status, run_chat_turn, stream_chat_turn

logger = logging.getLogger("query-api.assistant")

router = APIRouter(prefix="/assistant", tags=["assistant"])
# Router rieng KHONG gan require_admin (xem main.py): chi chua /assistant/health
# de trang "Trang thai he thong" doc duoc bang fetch thuong, giong cac
# /health khac. Khong dat endpoint co du lieu log/hoi thoai vao day.
public_router = APIRouter(prefix="/assistant", tags=["assistant"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def _require_cluster_store(request: Request):
    cluster_store = request.app.state.cluster_store
    if cluster_store is None:
        raise HTTPException(
            status_code=503,
            detail="cluster store chua san sang (can STORAGE_BACKEND=opensearch va OpenSearch dang chay)",
        )
    return cluster_store


def _require_conversation_repository(request: Request):
    repository = request.app.state.assistant_conversations
    if repository is None:
        raise HTTPException(status_code=503, detail="assistant storage chua san sang")
    return repository


def _get_cluster_or_404(cluster_store, cluster_id: str) -> dict:
    cluster = cluster_store.get_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    return cluster


@public_router.get("/health")
def assistant_health(request: Request):
    """Tinh trang AI Assistant cho trang "Trang thai he thong".

    LUON tra HTTP 200 (khong 503 nhu /health cua service): day khong phai
    healthcheck cua container, ma la 1 dong thong tin tren UI - tra 503 se
    khien UI chi hien "HTTP 503" thay vi ly do that trong `status`.

    KHONG goi Azure OpenAI o day (poll 15s/lan se ton phi) - chi doc cau hinh
    + ket qua lan goi that gan nhat (xem service.last_call_status).
    """
    if request.app.state.assistant_conversations is None:
        return {"status": "kho hội thoại chưa sẵn sàng", "service": "ai-assistant"}

    try:
        config.require_azure_openai_api_key()
    except ValueError as exc:
        return {"status": "chưa cấu hình", "service": "ai-assistant", "detail": str(exc)}

    last = last_call_status()
    if last["ok"] is False:
        return {"status": f"lỗi gọi gần nhất: {last['error']}", "service": "ai-assistant",
                "last_call_at": last["at"]}
    return {"status": "ok", "service": "ai-assistant",
            "model": config.AZURE_OPENAI_DEPLOYMENT, "last_call_at": last["at"]}


@router.get("/clusters/{cluster_id}/conversation")
def get_conversation(cluster_id: str, request: Request):
    """Hoi thoai dieu tra hien co cho 1 cum, hoac messages rong neu chua ai hoi AI lan nao."""
    cluster_store = _require_cluster_store(request)
    _get_cluster_or_404(cluster_store, cluster_id)

    repository = _require_conversation_repository(request)
    conversation = repository.get(cluster_id)
    return {"cluster_id": cluster_id, "messages": conversation["messages"] if conversation else []}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_events(repository, cluster_id: str, history: list[dict], created_at: str | None, turn: dict):
    """Day tung event cua 1 luot chat ra SSE: `delta` (doan chu model vua sinh),
    `tool` (ten tool AI dang tra cuu), roi `conversation` - TOAN BO hoi thoai da
    luu, dung shape voi response JSON de client dung chung mot cho xu ly.

    Loi o day KHONG the tra HTTP 502 duoc nua (header 200 da gui roi) nen bao
    bang event `error`; ca loi StorageError luc luu cung vay.
    """
    try:
        for event in stream_chat_turn(**turn):
            if "messages" not in event:
                yield _sse(event)
                continue
            saved = repository.save(cluster_id, history + event["messages"], created_at=created_at)
            yield _sse({"conversation": {"cluster_id": cluster_id, "messages": saved["messages"]}})
    except Exception as exc:  # noqa: BLE001 - giong nhanh JSON: khong lam sap service
        logger.exception("Assistant chat (stream) that bai cho cum %s", cluster_id)
        yield _sse({"error": f"AI Assistant loi: {type(exc).__name__}"})


@router.post("/clusters/{cluster_id}/conversation/messages")
def post_message(cluster_id: str, payload: ChatRequest, request: Request):
    """Gui 1 tin nhan, AI co the tu goi tool de dieu tra truoc khi tra loi.
    Tra ve TOAN BO hoi thoai (da luu) sau luot nay, khong chi tin nhan moi.

    Client gui `Accept: text/event-stream` thi nhan cung noi dung do duoi dang
    SSE, day dan tung doan chu (thay chu dau sau 1-2s thay vi doi het luot
    1-2 phut). Khong gui header do thi tra JSON y nhu truoc - CUNG mot
    endpoint, khong co endpoint moi.
    """
    cluster_store = _require_cluster_store(request)
    cluster = _get_cluster_or_404(cluster_store, cluster_id)

    try:
        config.require_azure_openai_api_key()
    except ValueError:
        raise HTTPException(
            status_code=503,
            detail="AI Assistant chua duoc cau hinh (thieu AZURE_OPENAI_API_KEY/AZURE_OPENAI_ENDPOINT)",
        ) from None

    store = request.app.state.store
    # Chi lay 5 log: system prompt chi nhung 5 log mau (xem
    # service._build_system_prompt) - lay 20 doc day du kem stack_trace la doc thua.
    logs = store.get_logs((cluster.get("log_ids") or [])[:5])

    repository = _require_conversation_repository(request)
    existing = repository.get(cluster_id)
    history = existing["messages"] if existing else []
    created_at = existing["created_at"] if existing else None

    turn = dict(cluster=cluster, logs=logs, history=history, user_message=payload.message,
                store=store, cluster_store=cluster_store, cluster_id=cluster_id)

    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            _sse_events(repository, cluster_id, history, created_at, turn),
            media_type="text/event-stream",
            # Chan buffer cua proxy dung giua (xem deploy/Caddyfile) - buffer lai
            # thi stream ve mot cuc o cuoi, mat dung cai dang can.
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        new_messages = run_chat_turn(**turn)
    except StorageError:
        raise
    except Exception as exc:  # noqa: BLE001 - loi tu OpenAI/Langfuse khong duoc lam sap service
        logger.exception("Assistant chat that bai cho cum %s", cluster_id)
        raise HTTPException(status_code=502, detail=f"AI Assistant loi: {type(exc).__name__}") from None

    saved = repository.save(cluster_id, history + new_messages, created_at=created_at)
    return {"cluster_id": cluster_id, "messages": saved["messages"]}
