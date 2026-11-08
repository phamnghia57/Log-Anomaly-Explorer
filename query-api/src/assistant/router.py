"""Endpoint AI Assistant - dieu tra & de xuat cach sua cho 1 cum, giong vai
tro cua Elastic Observability AI Assistant nhung thu gon cho du an nay (xem
README.md muc "AI Assistant"). JWT admin duoc gan cho ca router khi include
trong main.py, vi day la du lieu log/stack trace noi bo va goi API OpenAI co phi.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from ingestion.src.storage import StorageError

from . import config
from .service import run_chat_turn
from .storage import ConversationConflict, ConversationState, parse_revision

logger = logging.getLogger("query-api.assistant")

router = APIRouter(prefix="/assistant", tags=["assistant"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def meaningful_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Assistant message must not be blank")
        return value


class UndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictStr = Field(min_length=3, max_length=39)

    @field_validator("expected_revision")
    @classmethod
    def valid_revision(cls, value: str) -> str:
        parse_revision(value)
        return value


def _conversation_response(cluster_id: str, state: ConversationState | None) -> dict:
    return {
        "cluster_id": cluster_id,
        "messages": state.document["messages"] if state is not None else [],
        "revision": state.revision if state is not None else None,
        "undo_available": state is not None and state.document.get("undo") is not None,
    }


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
    return _conversation_response(cluster_id, conversation)


@router.post("/clusters/{cluster_id}/conversation/messages")
def post_message(cluster_id: str, payload: ChatRequest, request: Request):
    """Gui 1 tin nhan, AI co the tu goi tool de dieu tra truoc khi tra loi.
    Tra ve TOAN BO hoi thoai (da luu) sau luot nay, khong chi tin nhan moi."""
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
    logs = store.get_logs((cluster.get("log_ids") or [])[:20])

    repository = _require_conversation_repository(request)
    existing = repository.get(cluster_id)
    history = deepcopy(existing.document["messages"]) if existing is not None else []

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
    try:
        saved = repository.save(cluster_id, all_messages, previous=existing)
    except ConversationConflict as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from None
    return _conversation_response(cluster_id, saved)


@router.post("/clusters/{cluster_id}/conversation/undo")
def undo_send(cluster_id: str, payload: UndoRequest, request: Request):
    cluster_store = _require_cluster_store(request)
    _get_cluster_or_404(cluster_store, cluster_id)
    repository = _require_conversation_repository(request)
    try:
        restored = repository.undo(cluster_id, payload.expected_revision)
    except ConversationConflict as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from None
    return _conversation_response(cluster_id, restored)
