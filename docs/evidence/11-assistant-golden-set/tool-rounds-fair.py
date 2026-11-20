"""Phep do bo sung cho #108: so rounds=1 vs rounds=2 KHI TRACE CON TON TAI.

Hai luot chinh (scores-round1/2.csv) chay tren 4 cum tu 2026-11-14, ma Jaeger
da mat het span cua chung (volume Badger moi tao o Task 10) -> ca 4 lan goi
tool deu tra "trace not found". Trong dieu kien do, rounds=2 khong the hien
duoc gia tri that cua no. Script nay do lai tren mot cum CO trace song.

Khong doi env/recreate container: `config.MAX_TOOL_ROUNDS` doc luc import nen
chi can gan lai thuoc tinh module truoc moi luot - tuong duong ve hanh vi va
khong lam gian doan service.

Chay:  docker compose exec -T query-api python /tmp/tool_rounds_fair.py
"""
import importlib
import json
import os
import time

import httpx

from clustering.src.storage import OpenSearchStore
from ingestion.src.storage import build_store

svc = importlib.import_module("query-api.src.assistant.service")
cfg = importlib.import_module("query-api.src.assistant.config")

SIGNATURE = "simulated downstream failure"
SERVICE = "demo-web"
QUESTION = ("Neu co the doc trace cua mot request trong cum, span nao loi va "
            "HTTP status nao duoc ghi nhan?")
OUT = "/tmp/tool-rounds-fair.json"

store = build_store()
cluster_store = OpenSearchStore()
opensearch = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")
cluster_index = os.environ.get("CLUSTER_INDEX", "clusters")

query = {"size": 5, "query": {"bool": {"filter": [
    {"term": {"service": SERVICE}}, {"term": {"signature": SIGNATURE}}]}}}
hits = httpx.post(f"{opensearch}/{cluster_index}/_search", json=query, timeout=20).json()
docs = [h["_source"] for h in hits.get("hits", {}).get("hits", [])]
if not docs:
    raise SystemExit("khong tim thay cum cho signature: " + SIGNATURE)
cluster = docs[0]
logs = store.get_logs((cluster.get("log_ids") or [])[:5])

# Xac minh trace cua log mau THAT SU co trong Jaeger - neu khong thi phep do
# nay lai roi vao dung cai bay cua hai luot chinh.
jaeger = os.environ.get("JAEGER_QUERY_URL", "").rstrip("/")
alive = []
for log in logs:
    trace_id = log.get("trace_id")
    if not trace_id:
        continue
    response = httpx.get(f"{jaeger}/api/traces/{trace_id}", timeout=15)
    found = response.status_code == 200 and bool((response.json() or {}).get("data"))
    alive.append({"trace_id": trace_id, "trong_jaeger": found})

report = {
    "cluster_id": cluster["cluster_id"],
    "service": cluster.get("service"),
    "signature": cluster.get("signature"),
    "score": cluster.get("score"),
    "status": cluster.get("status"),
    "last_seen": cluster.get("last_seen"),
    "so_log_mau": len(logs),
    "trace_cua_log_mau": alive,
    "so_trace_con_song": sum(1 for a in alive if a["trong_jaeger"]),
    "question": QUESTION,
    "git_sha": os.environ.get("GIT_SHA"),
    "runs": [],
}
print("cum:", report["cluster_id"], "score", report["score"],
      "| trace con song:", report["so_trace_con_song"], "/", len(alive), flush=True)
if report["so_trace_con_song"] == 0:
    print("CANH BAO: khong co trace nao con song -> phep do nay vo nghia", flush=True)

original = cfg.MAX_TOOL_ROUNDS
try:
    for rounds in (1, 2):
        cfg.MAX_TOOL_ROUNDS = rounds
        for attempt in (1, 2):
            started = time.perf_counter()
            messages = svc.run_chat_turn(
                cluster=cluster, logs=logs, history=[], user_message=QUESTION,
                store=store, cluster_store=cluster_store, cluster_id=cluster["cluster_id"])
            answer = next((m.get("content") or "" for m in reversed(messages)
                           if m.get("role") == "assistant" and m.get("content")), "")
            tools = [m.get("name") for m in messages if m.get("role") == "tool"]
            tool_results = [(m.get("content") or "")[:200] for m in messages if m.get("role") == "tool"]
            report["runs"].append({
                "max_tool_rounds": rounds, "lan": attempt,
                "goi_tool": tools, "ket_qua_tool": tool_results,
                "do_tre_s": round(time.perf_counter() - started, 2),
                "answer": answer,
            })
            print(f"rounds={rounds} lan {attempt}: tools={tools} "
                  f"{round(time.perf_counter() - started, 2)}s", flush=True)
            time.sleep(8)
finally:
    cfg.MAX_TOOL_ROUNDS = original

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2)
cluster_store.close()
print("da ghi " + OUT)
