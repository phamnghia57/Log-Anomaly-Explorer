"""Endpoint AI Assistant - dieu tra & de xuat cach sua cho 1 cum, giong vai
tro cua Elastic Observability AI Assistant nhung thu gon cho du an nay (xem
README.md muc "AI Assistant"). JWT admin duoc gan cho ca router khi include
trong main.py, vi day la du lieu log/stack trace noi bo va goi API OpenAI co phi.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ingestion.src.storage import StorageError

from . import config
from .service import run_chat_turn

logger = logging.getLogger("query-api.assistant")

router = APIRouter(prefix="/assistant", tags=["assistant"])


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


@router.get("/clusters/{cluster_id}/conversation")
def get_conversation(cluster_id: str, request: Request):
    """Hoi thoai dieu tra hien co cho 1 cum, hoac messages rong neu chua ai hoi AI lan nao."""
    cluster_store = _require_cluster_store(request)
    _get_cluster_or_404(cluster_store, cluster_id)

    repository = _require_conversation_repository(request)
    conversation = repository.get(cluster_id)
    return {"cluster_id": cluster_id, "messages": conversation["messages"] if conversation else []}


@router.post("/clusters/{cluster_id}/conversation/messages")
def post_message(cluster_id: str, payload: ChatRequest, request: Request):
    """Gui 1 tin nhan, AI co the tu goi tool de dieu tra truoc khi tra loi.
    Tra ve TOAN BO hoi thoai (da luu) sau luot nay, khong chi tin nhan moi."""
    cluster_store = _require_cluster_store(request)
    cluster = _get_cluster_or_404(cluster_store, cluster_id)

    try:
        config.require_openai_api_key()
    except ValueError:
        raise HTTPException(
            status_code=503, detail="AI Assistant chua duoc cau hinh (thieu OPENAI_API_KEY)",
        ) from None

    store = request.app.state.store
    logs = store.get_logs((cluster.get("log_ids") or [])[:20])

    repository = _require_conversation_repository(request)
    existing = repository.get(cluster_id)
    history = existing["messages"] if existing else []

    try:
        new_messages = run_chat_turn(
            cluster=cluster, logs=logs, history=history, user_message=payload.message,
            store=store, cluster_store=cluster_store, cluster_id=cluster_id,
        )
    except StorageError:
        raise
    except Exception as exc:  # noqa: BLE001 - loi tu OpenAI/Langfuse khong duoc lam sap service
        logger.exception("Assistant chat that bai cho cum %s", cluster_id)
        raise HTTPException(status_code=502, detail=f"AI Assistant loi: {type(exc).__name__}") from None

    all_messages = history + new_messages
    saved = repository.save(cluster_id, all_messages, created_at=existing["created_at"] if existing else None)
    return {"cluster_id": cluster_id, "messages": saved["messages"]}
