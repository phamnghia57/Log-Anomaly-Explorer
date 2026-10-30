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
from datetime import datetime, timezone

from langfuse.openai import AzureOpenAI

from . import config
from .tools import TOOL_SCHEMAS, ToolExecutor

logger = logging.getLogger("query-api.assistant")

SYSTEM_PROMPT_TEMPLATE = """Ban la AI Assistant dieu tra loi he thong cho du an "Log Anomaly \
Explorer", dong vai tro giong Elastic Observability AI Assistant: giai thich loi va de xuat \
cach sua DUA TREN DU LIEU THAT, khong bia dat thong tin khong co trong du lieu/cong cu.

Thong tin cum dang dieu tra (cluster_id={cluster_id}):
- service: {service}
- signature (message da chuan hoa): {signature}
- anomaly score: {score} (nguong bao dong hien tai: {threshold})
- status: {status}
- tong so log thuoc cum: {log_count}
- log mau (toi da 5, kem stack_trace neu co):
{sample_logs}

Dung tool khi can them thong tin truoc khi ket luan: get_cluster_history (xu huong score cua \
chinh cum nay theo thoi gian), search_related_logs (log khac co lien quan), list_active_clusters \
(cum khac dang bat thuong cung luc - kiem tra su co co lan sang service khac khong).

Luon trich dan bang chung cu the (service, thoi diem, message) khi ket luan. Neu khong du du \
lieu de chac chan, noi ro la khong chac chan thay vi doan. Tra loi bang tieng Viet, ngan gon, \
co cau truc ro rang: Nguyen nhan co the - Bang chung - De xuat huong xu ly."""


def _build_system_prompt(cluster: dict, logs: list[dict]) -> str:
    sample = logs[:5]
    sample_text = "\n".join(
        f"  [{item.get('timestamp')}] {item.get('service')}: {item.get('message')}"
        + (f"\n    stack_trace: {item['stack_trace']}" if item.get("stack_trace") else "")
        for item in sample
    ) or "  (khong co log mau)"
    service = next((log.get("service") for log in logs if log.get("service")), "unknown")
    return SYSTEM_PROMPT_TEMPLATE.format(
        cluster_id=cluster.get("cluster_id"),
        service=service,
        signature=cluster.get("signature") or "(khong co)",
        score=cluster.get("score"),
        threshold=config.ANOMALY_THRESHOLD_HINT,
        status=cluster.get("status"),
        log_count=len(cluster.get("log_ids") or []),
        sample_logs=sample_text,
    )


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


def run_chat_turn(
    *, cluster: dict, logs: list[dict], history: list[dict], user_message: str,
    store, cluster_store, cluster_id: str,
) -> list[dict]:
    """Them user_message vao hoi thoai, goi OpenAI (co the goi tool nhieu
    vong), tra ve DANH SACH message MOI can luu them (bao gom ca user_message
    dau tien) - khong bao gom `history` (goi lai da truyen vao).
    """
    api_key = config.require_azure_openai_api_key()
    client = AzureOpenAI(
        api_key=api_key,
        azure_endpoint=config.azure_openai_endpoint(),
        api_version=config.AZURE_OPENAI_API_VERSION,
    )
    executor = ToolExecutor(store=store, cluster_store=cluster_store, cluster_id=cluster_id)

    new_messages: list[dict] = [
        {"role": "user", "content": user_message, "created_at": datetime.now(timezone.utc).isoformat()},
    ]

    openai_messages: list[dict] = [{"role": "system", "content": _build_system_prompt(cluster, logs)}]
    for entry in history + new_messages:
        openai_messages.append(_to_openai_message(entry))

    for round_index in range(config.MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=config.AZURE_OPENAI_DEPLOYMENT,
            messages=openai_messages,
            tools=TOOL_SCHEMAS,
            max_tokens=config.MAX_OUTPUT_TOKENS,
            metadata={
                "langfuse_tags": ["log-anomaly-explorer", "incident-assistant"],
                "langfuse_session_id": cluster_id,
            },
        )
        message = response.choices[0].message

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
            "content": "Da dat gioi han so lan tra cuu cho 1 luot hoi - vui long hoi cu the hon "
                       "hoac tiep tuc o tin nhan sau.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:  # noqa: BLE001 - khong de loi flush trace lam hong response that da co
        logger.exception("Khong flush duoc Langfuse trace")

    return new_messages
