"""Chay 1 luot chat voi AI Assistant: goi Azure OpenAI (qua Langfuse de tu
dong trace chi phi/do tre/token - xem README.md muc "AI Assistant"), cho phep
AI tu goi tool de dieu tra them, lap lai toi da ASSISTANT_MAX_TOOL_ROUNDS
vong truoc khi bat buoc dung (bao ve chi phi/do tre, tranh vong lap vo diem
dung).

Dung Azure OpenAI thay vi OpenAI truc tiep: VM chay o vung Azure "East Asia"
(Hong Kong) bi OpenAI chan theo IP - xem
docs/architect/contracts/api-contract.md muc "AI Assistant".
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace

from langfuse.openai import OpenAI

from . import config
from .tools import MAX_STACK_TRACE_CHARS, TOOL_SCHEMAS, ToolExecutor

logger = logging.getLogger("query-api.assistant")

# Client OpenAI dung lai giua cac request: moi lan khoi tao moi la 1 connection
# pool httpx moi + 1 bat tay TLS moi + init lai wrapper Langfuse, cong vao do
# tre cua MOI tin nhan chat. Key co ca `OpenAI` (callable duoc tra cuu luc goi)
# chu khong chi config: test monkeypatch `service.OpenAI` thanh factory rieng o
# tung test, cache chi theo config se tra ve client cua test truoc.
_clients: dict[tuple, object] = {}


def _get_client():
    api_key = config.require_azure_openai_api_key()
    base_url = config.azure_openai_v1_base_url()
    timeout = config.AZURE_OPENAI_TIMEOUT_SECONDS
    key = (OpenAI, api_key, base_url, timeout)
    client = _clients.get(key)
    if client is None:
        client = _clients[key] = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    return client

# Ket qua lan goi Azure OpenAI GAN NHAT, giu trong bo nho process. Dung cho
# GET /assistant/health: trang "Trang thai he thong" poll 15s/lan nen KHONG
# duoc goi that moi lan kiem tra (ton tien + cham) - thay vao do bao lai ket
# qua that gan nhat, du de phat hien het quota / bi chan vung / sai cau hinh.
# Restart process thi ve lai None (chua goi lan nao) - chap nhan duoc.
_last_call: dict[str, object | None] = {"ok": None, "error": None, "at": None}


def _record_call(ok: bool, error: str | None = None) -> None:
    _last_call.update(ok=ok, error=error, at=datetime.now(timezone.utc).isoformat())


def last_call_status() -> dict:
    """Ban sao trang thai lan goi gan nhat; `ok=None` = chua goi lan nao."""
    return dict(_last_call)

SYSTEM_PROMPT_TEMPLATE = """Bạn là AI Assistant điều tra lỗi hệ thống cho dự án "Log Anomaly \
Explorer", đóng vai trò giống Elastic Observability AI Assistant: giải thích lỗi và đề xuất \
cách sửa DỰA TRÊN DỮ LIỆU THẬT, không bịa đặt thông tin không có trong dữ liệu/công cụ.

Thông tin cụm đang điều tra (cluster_id={cluster_id}):
- service: {service}
- signature (message đã chuẩn hoá): {signature}
- anomaly score: {score} (ngưỡng báo động hiện tại: {threshold})
- status: {status}
- tổng số log thuộc cụm: {log_count}
- log mẫu (tối đa 5, kèm stack_trace nếu có):
{sample_logs}

Đây là môi trường demo: log được tạo/bơm tự động để kiểm thử, không phải sự cố sản xuất \
thật. Ưu tiên trả lời trực tiếp từ sample log/stack_trace đã có ở trên - thường là đủ để nêu \
nguyên nhân cơ bản. Chỉ gọi tool khi sample log thực sự không đủ để trả lời; không gọi nhiều \
tool liên tiếp để điều tra sâu khi đã có thể trả lời thẳng từ dữ liệu sẵn có.

Bạn KHÔNG có quyền truy cập mã nguồn, lịch sử Git, hay thông tin triển khai/deploy. Nếu được \
hỏi về commit/deploy gần nhất hoặc cần xem mã nguồn cụ thể, nói rõ bạn không có dữ liệu đó \
thay vì cố đoán, và chỉ tập trung trả lời phần câu hỏi có thể trả lời được từ log/cụm hiện có.

Luôn trích dẫn bằng chứng cụ thể (service, thời điểm, message) khi kết luận. Nếu không đủ dữ \
liệu để chắc chắn, nói rõ là không chắc chắn thay vì đoán. Trả lời bằng tiếng Việt có dấu, \
ngắn gọn, có cấu trúc rõ ràng: Nguyên nhân có thể - Bằng chứng - Đề xuất hướng xử lý."""


def _build_system_prompt(cluster: dict, logs: list[dict]) -> str:
    sample = logs[:5]
    sample_text = "\n".join(
        f"  [{item.get('timestamp')}] {item.get('service')}: {item.get('message')}"
        + (f"\n    stack_trace: {item['stack_trace'][:MAX_STACK_TRACE_CHARS]}"
           if item.get("stack_trace") else "")
        for item in sample
    ) or "  (không có log mẫu)"
    service = next((log.get("service") for log in logs if log.get("service")), "unknown")
    return SYSTEM_PROMPT_TEMPLATE.format(
        cluster_id=cluster.get("cluster_id"),
        service=service,
        signature=cluster.get("signature") or "(không có)",
        score=cluster.get("score"),
        threshold=config.ANOMALY_THRESHOLD_HINT,
        status=cluster.get("status"),
        log_count=len(cluster.get("log_ids") or []),
        sample_logs=sample_text,
    )


def _trim_history(history: list[dict], limit: int) -> list[dict]:
    """Chi giu toi da `limit` message cu gan nhat de GUI len model.

    Hoi thoai van duoc LUU day du (router.py luu `history + new_messages`) -
    gioi han nay chi cho phan ngu canh gui di, vi moi luot deu gui lai toan bo
    lich su nen chi phi token tang dan theo do dai hoi thoai.

    Sau khi cat, BO tiep cac message dau cho den khi gap mot message `user`:
    message `tool` chi hop le khi di ngay sau assistant message co `tool_calls`
    sinh ra no, cat ngang chuoi do se lam API tra 400. Bat dau tu mot luot hoi
    cua nguoi dung thi luon an toan.
    """
    if len(history) <= limit:
        return history
    trimmed = history[-limit:]
    for index, entry in enumerate(trimmed):
        if entry.get("role") == "user":
            return trimmed[index:]
    return []


def _to_openai_message(entry: dict) -> dict:
    """Chuyen 1 message da luu (dinh dang cua assistant-conversation-schema.json)
    ve dung dinh dang OpenAI chat API mong doi."""
    if entry["role"] == "tool":
        return {"role": "tool", "tool_call_id": entry["tool_call_id"], "content": entry["content"]}
    message: dict = {"role": entry["role"], "content": entry.get("content")}
    if entry.get("tool_calls"):
        message["tool_calls"] = [
            {"id": tc["id"], "type": "function",
             "function": {"name": tc["name"], "arguments": tc["arguments"]}}
            for tc in entry["tool_calls"]
        ]
    return message


def _collect_stream(response) -> Iterator[dict]:
    """Gom cac chunk cua mot lan goi stream=True thanh MOT message co cung hinh
    dang voi ban non-stream (`.content`, `.tool_calls`), dong thoi yield tung
    doan chu ngay khi model sinh ra de router day ra SSE.

    Dung SimpleNamespace thay vi dinh nghia class rieng: chi can du thuoc tinh
    cho doan code xu ly message o duoi dung chung cho ca 2 che do, khong them
    mot tang kieu du lieu chi de sao chep lai dang cua SDK.
    """
    content: list[str] = []
    calls: dict[int, dict] = {}
    for chunk in response:
        if not chunk.choices:
            continue  # chunk cuoi chi chua usage/content filter, khong co delta
        delta = chunk.choices[0].delta
        if delta.content:
            content.append(delta.content)
            yield {"delta": delta.content}
        for part in delta.tool_calls or []:
            # tool_calls ve rai rac theo `index`: id/name o chunk dau, arguments
            # noi dan tung manh JSON o cac chunk sau.
            call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
            if part.id:
                call["id"] = part.id
            if part.function and part.function.name:
                call["name"] = part.function.name
            if part.function and part.function.arguments:
                call["arguments"] += part.function.arguments
    return SimpleNamespace(
        content="".join(content) or None,
        tool_calls=[
            SimpleNamespace(id=call["id"],
                            function=SimpleNamespace(name=call["name"], arguments=call["arguments"]))
            for _index, call in sorted(calls.items())
        ] or None,
    )


def run_chat_turn(
    *, cluster: dict, logs: list[dict], history: list[dict], user_message: str,
    store, cluster_store, cluster_id: str,
) -> list[dict]:
    """Them user_message vao hoi thoai, goi OpenAI (co the goi tool nhieu
    vong), tra ve DANH SACH message MOI can luu them (bao gom ca user_message
    dau tien) - khong bao gom `history` (goi lai da truyen vao).
    """
    for event in stream_chat_turn(
        cluster=cluster, logs=logs, history=history, user_message=user_message,
        store=store, cluster_store=cluster_store, cluster_id=cluster_id, stream=False,
    ):
        if "messages" in event:
            return event["messages"]
    return []  # khong bao gio xay ra: stream_chat_turn luon ket thuc bang event messages


def stream_chat_turn(
    *, cluster: dict, logs: list[dict], history: list[dict], user_message: str,
    store, cluster_store, cluster_id: str, stream: bool = True,
) -> Iterator[dict]:
    """Nhu run_chat_turn nhung tra ve lan luot cac event de day ra SSE:
    `{"delta": "<doan chu>"}`, `{"tool": "<ten tool>"}`, va cuoi cung
    `{"messages": [...]}` (danh sach message moi can luu, giong run_chat_turn).

    `stream=False` goi Azure OpenAI y nhu truoc (KHONG truyen stream=True) va
    chi yield event `messages` cuoi cung - do la duong di cua nhanh JSON cu.
    """
    client = _get_client()
    executor = ToolExecutor(store=store, cluster_store=cluster_store, cluster_id=cluster_id)

    new_messages: list[dict] = [
        {"role": "user", "content": user_message, "created_at": datetime.now(timezone.utc).isoformat()},
    ]

    openai_messages: list[dict] = [{"role": "system", "content": _build_system_prompt(cluster, logs)}]
    for entry in _trim_history(history, config.MAX_HISTORY_MESSAGES) + new_messages:
        openai_messages.append(_to_openai_message(entry))

    for round_index in range(config.MAX_TOOL_ROUNDS):
        # Vong CUOI khong gui `tools`: neu con tool thi model co the lai doi tra
        # cuu them va het luot ma chua tra loi - mat them 1 lan goi model chi de
        # nhan ve cau "da dat gioi han". Vong cuoi buoc phai tra loi bang chu.
        tools = {"tools": TOOL_SCHEMAS} if round_index < config.MAX_TOOL_ROUNDS - 1 else {}
        try:
            response = client.chat.completions.create(
                model=config.AZURE_OPENAI_DEPLOYMENT,
                messages=openai_messages,
                **tools,
                # include_usage: chunk cuoi cua stream moi mang so token - thieu
                # no thi Langfuse khong tinh duoc token/chi phi cho cac luot
                # stream (xem README.md muc "AI Assistant").
                **({"stream": True, "stream_options": {"include_usage": True}} if stream else {}),
                max_completion_tokens=config.MAX_OUTPUT_TOKENS,
                reasoning_effort=config.ASSISTANT_REASONING_EFFORT,
                metadata={
                    "langfuse_tags": ["log-anomaly-explorer", "incident-assistant"],
                    "langfuse_session_id": cluster_id,
                },
            )
            # Khi stream, loi mang/quota chi noi len luc doc chunk nen phan gom
            # chunk phai nam trong cung try de _record_call(False) khong bi bo sot.
            message = (yield from _collect_stream(response)) if stream else response.choices[0].message
        except Exception as exc:  # noqa: BLE001 - ghi nhan roi nem tiep cho router xu ly
            _record_call(False, type(exc).__name__)
            raise
        _record_call(True)

        assistant_entry: dict = {
            "role": "assistant",
            "content": message.content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if message.tool_calls:
            assistant_entry["tool_calls"] = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in message.tool_calls
            ]
        new_messages.append(assistant_entry)
        openai_messages.append(_to_openai_message(assistant_entry))

        if not message.tool_calls:
            break

        for tool_call in message.tool_calls:
            yield {"tool": tool_call.function.name}
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            result = executor.run(tool_call.function.name, arguments)
            tool_entry = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": json.dumps(result, ensure_ascii=False),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            new_messages.append(tool_entry)
            openai_messages.append(_to_openai_message(tool_entry))
    else:
        logger.warning(
            "Assistant dat gioi han %s vong goi tool cho cum %s (round=%s)",
            config.MAX_TOOL_ROUNDS, cluster_id, round_index,
        )
        new_messages.append({
            "role": "assistant",
            "content": "Đã đạt giới hạn số lần tra cứu cho 1 lượt hỏi - vui lòng hỏi cụ thể hơn "
                       "hoặc tiếp tục ở tin nhắn sau.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    # KHONG flush Langfuse dong bo o day: flush() la 1 round trip HTTPS sang
    # Langfuse cloud (khac vung voi VM) cong vao do tre cua MOI tin nhan chat,
    # trong khi SDK da tu gui nen theo batch + flush luc atexit. Danh doi: neu
    # process bi kill ngay sau khi tra loi thi trace cua luot do co the mat.
    yield {"messages": new_messages}
