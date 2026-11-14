"""Test cho AI Assistant: chat loop (tool calling), persistence qua
ConversationRepository gia, va endpoint /assistant/*.

Khong goi OpenAI/Langfuse that: mock lop client (OpenAI tu service.py goi)
de kiem soat kich ban (tra loi thang, hoac goi tool truoc khi tra loi).
Dung STORAGE_BACKEND=memory (xem conftest.py) nen khong can OpenSearch that -
cluster_store/assistant_conversations trong app.state duoc thay bang fake.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

main = importlib.import_module("query-api.src.main")
assistant_config = importlib.import_module("query-api.src.assistant.config")
assistant_service = importlib.import_module("query-api.src.assistant.service")
assistant_tools = importlib.import_module("query-api.src.assistant.tools")

client = TestClient(main.app)


# --------------------------------------------------------------------------- fakes: data layer

class FakeClusterStore:
    def __init__(self, records=None, history=None):
        self.records = list(records or [])
        self.history = list(history or [])

    def get_cluster(self, cluster_id):
        return next((r for r in self.records if r["cluster_id"] == cluster_id), None)

    def list_clusters(self, *, status=None, since=None, limit=100, offset=0):
        results = [r for r in self.records if status is None or r["status"] == status]
        return results[offset:offset + limit]

    def list_history(self, cluster_id, *, since=None, limit=100):
        return list(self.history)


class FakeConversationRepository:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def get(self, cluster_id):
        return self.docs.get(cluster_id)

    def save(self, cluster_id, messages, *, created_at=None):
        now = datetime.now(timezone.utc).isoformat()
        document = {"cluster_id": cluster_id, "created_at": created_at or now,
                    "updated_at": now, "messages": messages}
        self.docs[cluster_id] = document
        return document


def record(cluster_id="c1", **over):
    base = {"cluster_id": cluster_id, "signature": "simulated failure in checkout", "score": 5.0,
            "log_ids": ["log-1"], "trace_ids": ["t1"],
            "first_seen": "2026-10-29T00:00:00+00:00", "last_seen": "2026-10-29T00:05:00+00:00",
            "status": "anomalous"}
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _reset_store(admin_auth):
    original_headers = client.headers.copy()
    client.headers.update(admin_auth)
    main.store._logs.clear()
    yield
    client.headers = original_headers


def write(log_id: str, **over) -> None:
    # Thoi diem TUONG DOI (khong co dinh): search_related_logs mac dinh chi
    # tim 24h gan nhat, moc thoi gian co dinh se tu roi ra ngoai cua so khi
    # thoi gian troi qua - cung bay da tranh o test_query_api.py::iso().
    log = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": "ERROR", "service": "demo-web",
           "trace_id": "t1", "span_id": "s1", "message": "Simulated failure in checkout"}
    log.update(over)
    main.store.write_log(log_id, log)


@pytest.fixture
def clusters():
    # KHONG dung monkeypatch.setattr tren app.state: starlette.datastructures.State
    # luu attribute trong dict noi bo (khong phai __dict__ that), khien
    # monkeypatch xac dinh sai "gia tri cu" roi goi delattr() luc undo thay vi
    # setattr() - lam MAT attribute hoan toan cho test sau (da tu kiem chung
    # bug nay truc tiep voi starlette.datastructures.State + pytest monkeypatch).
    # Tu patch/restore thu cong de tranh.
    fake = FakeClusterStore()
    original = main.app.state.cluster_store
    main.app.state.cluster_store = fake
    yield fake
    main.app.state.cluster_store = original


@pytest.fixture
def conversations():
    fake = FakeConversationRepository()
    original = main.app.state.assistant_conversations
    main.app.state.assistant_conversations = fake
    yield fake
    main.app.state.assistant_conversations = original


@pytest.fixture
def azure_openai_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake-resource.openai.azure.com/")


@pytest.mark.parametrize("method,path", [
    ("GET", "/assistant/clusters/c1/conversation"),
    ("POST", "/assistant/clusters/c1/conversation/messages"),
])
@pytest.mark.parametrize("authorization", [None, "Bearer invalid"])
def test_assistant_requires_admin_before_storage_or_openai(method, path, authorization):
    client.headers.pop("Authorization", None)
    if authorization:
        client.headers["Authorization"] = authorization
    response = client.request(method, path, json={"message": "hi"} if method == "POST" else None)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


# --------------------------------------------------------------------------- fake OpenAI client

class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.function = _FakeFunction(name, arguments)


def fake_message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def fake_response(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAI:
    """Thay the langfuse.openai.OpenAI (tro vao Azure qua base_url) trong
    test: tra ve lan luot cac response da chuan bi san, ghi lai moi lan goi
    de kiem tra messages/tools truyen vao dung."""

    def __init__(self, responses, *, api_key=None, base_url=None, timeout=None):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeOpenAI het response da chuan bi - goi qua nhieu lan")
        return self._responses.pop(0)


def patch_openai(monkeypatch, responses):
    holder: dict[str, FakeOpenAI] = {}

    def factory(*, api_key=None, base_url=None, timeout=None):
        fake = FakeOpenAI(responses, api_key=api_key, base_url=base_url, timeout=timeout)
        holder["instance"] = fake
        return fake

    monkeypatch.setattr(assistant_service, "OpenAI", factory)
    return holder


# --------------------------------------------------------------------------- GET conversation

class TestGetConversation:
    def test_cum_khong_ton_tai_tra_404(self, clusters):
        assert client.get("/assistant/clusters/khong-co/conversation").status_code == 404

    def test_chua_hoi_lan_nao_tra_messages_rong(self, clusters, conversations):
        clusters.records = [record("c1")]
        body = client.get("/assistant/clusters/c1/conversation").json()
        assert body == {"cluster_id": "c1", "messages": []}

    def test_tra_ve_hoi_thoai_da_luu(self, clusters, conversations):
        clusters.records = [record("c1")]
        conversations.docs["c1"] = {
            "cluster_id": "c1", "created_at": "2026-10-29T00:00:00+00:00",
            "updated_at": "2026-10-29T00:00:00+00:00",
            "messages": [{"role": "user", "content": "hi", "created_at": "2026-10-29T00:00:00+00:00"}],
        }
        body = client.get("/assistant/clusters/c1/conversation").json()
        assert body["messages"][0]["content"] == "hi"


# --------------------------------------------------------------------------- POST message

class TestPostMessage:
    def test_cum_khong_ton_tai_tra_404(self, clusters, conversations, azure_openai_env):
        resp = client.post("/assistant/clusters/khong-co/conversation/messages", json={"message": "hi"})
        assert resp.status_code == 404

    def test_thieu_openai_key_tra_503(self, clusters, conversations, monkeypatch):
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        clusters.records = [record("c1")]
        resp = client.post("/assistant/clusters/c1/conversation/messages", json={"message": "hi"})
        assert resp.status_code == 503

    def test_tra_loi_thang_khong_can_goi_tool(self, clusters, conversations, azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        write("log-1", stack_trace="Traceback...")
        holder = patch_openai(monkeypatch, [
            fake_response(fake_message(content="Nguyen nhan co the la ... De xuat: ...")),
        ])

        resp = client.post("/assistant/clusters/c1/conversation/messages", json={"message": "Loi nay la gi?"})

        assert resp.status_code == 200
        body = resp.json()
        roles = [m["role"] for m in body["messages"]]
        assert roles == ["user", "assistant"]
        assert body["messages"][0]["content"] == "Loi nay la gi?"
        assert "De xuat" in body["messages"][1]["content"]
        # Luu lai dung nhu da tra ve - goi lai GET phai thay y het.
        assert client.get("/assistant/clusters/c1/conversation").json() == body
        # System prompt phai chua du lieu that cua cum (khong bia dat).
        sent_messages = holder["instance"].calls[0]["messages"]
        assert sent_messages[0]["role"] == "system"
        assert "simulated failure in checkout" in sent_messages[0]["content"]
        assert "c1" in sent_messages[0]["content"]

    def test_ai_goi_tool_truoc_khi_tra_loi(self, clusters, conversations, azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        clusters.history = [{"cluster_id": "c1", "score": 1.0, "status": "normal",
                             "recorded_at": "2026-10-29T00:00:00+00:00"}]
        write("log-1")

        tool_call = _FakeToolCall("call_1", "get_cluster_history", "{}")
        holder = patch_openai(monkeypatch, [
            fake_response(fake_message(content=None, tool_calls=[tool_call])),
            fake_response(fake_message(content="Score dang tang dan theo thoi gian.")),
        ])

        resp = client.post("/assistant/clusters/c1/conversation/messages",
                           json={"message": "Xu huong the nao?"})

        assert resp.status_code == 200
        roles = [m["role"] for m in resp.json()["messages"]]
        assert roles == ["user", "assistant", "tool", "assistant"]
        tool_msg = resp.json()["messages"][2]
        assert tool_msg["name"] == "get_cluster_history"
        assert "recorded_at" in tool_msg["content"]  # ket qua that cua list_history, khong bia
        assert len(holder["instance"].calls) == 2  # goi OpenAI 2 vong: co tool roi khong con tool

    def test_dat_gioi_han_vong_goi_tool(self, clusters, conversations, azure_openai_env, monkeypatch):
        monkeypatch.setattr(assistant_config, "MAX_TOOL_ROUNDS", 2)
        clusters.records = [record("c1")]

        def always_tool_call(**_kwargs):
            return fake_response(fake_message(
                content=None, tool_calls=[_FakeToolCall("call_x", "get_cluster_history", "{}")],
            ))

        calls = []

        def factory(*, api_key=None, base_url=None, timeout=None):
            fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kw: (calls.append(kw), always_tool_call())[1],
            )))
            return fake

        monkeypatch.setattr(assistant_service, "OpenAI", factory)

        resp = client.post("/assistant/clusters/c1/conversation/messages", json={"message": "?"})

        assert resp.status_code == 200
        assert len(calls) == 2  # dung dung MAX_TOOL_ROUNDS, khong lap vo han
        last_message = resp.json()["messages"][-1]
        assert last_message["role"] == "assistant"
        assert "giới hạn" in last_message["content"]

    def test_hoi_tiep_gui_kem_lich_su_cu(self, clusters, conversations, azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        conversations.docs["c1"] = {
            "cluster_id": "c1", "created_at": "2026-10-29T00:00:00+00:00",
            "updated_at": "2026-10-29T00:00:00+00:00",
            "messages": [
                {"role": "user", "content": "Lan truoc hoi gi?", "created_at": "2026-10-29T00:00:00+00:00"},
                {"role": "assistant", "content": "Da tra loi A.", "created_at": "2026-10-29T00:00:01+00:00"},
            ],
        }
        holder = patch_openai(monkeypatch, [fake_response(fake_message(content="Tiep tuc B."))])

        resp = client.post("/assistant/clusters/c1/conversation/messages", json={"message": "Con gi nua?"})

        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 4  # 2 cu + user moi + assistant moi
        sent = holder["instance"].calls[0]["messages"]
        contents = [m.get("content") for m in sent]
        assert "Lan truoc hoi gi?" in contents
        assert "Da tra loi A." in contents
        assert "Con gi nua?" in contents


# --------------------------------------------------------------------------- ToolExecutor (unit)

class FakeJaegerResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def jaeger_trace(span_count=2):
    spans = [{
        "spanID": f"s{index}", "operationName": f"GET /step-{index}", "processID": "p1",
        "startTime": 1000 - index, "duration": 2000, "tags": [],
    } for index in range(span_count)]
    return {"data": [{
        "traceID": "a" * 32, "processes": {"p1": {"serviceName": "demo-web"}}, "spans": spans,
    }]}


class TestToolExecutor:
    def test_tool_khong_ton_tai_tra_error_khong_nem_exception(self):
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=None, cluster_id="c1")
        assert executor.run("khong_co_tool_nay", {}) == {"error": "unknown tool: khong_co_tool_nay"}

    def test_get_cluster_history_khong_co_cluster_store_tra_error(self):
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=None, cluster_id="c1")
        assert executor.run("get_cluster_history", {}) == {"error": "cluster store unavailable"}

    def test_search_related_logs_mac_dinh_24h_va_gioi_han_limit(self):
        write("log-1")
        executor = assistant_tools.ToolExecutor(store=main.store, cluster_store=None, cluster_id="c1")
        result = executor.run("search_related_logs", {"limit": 999})
        assert result["total"] == 1
        assert len(result["results"]) == 1

    def test_list_active_clusters_loc_theo_status(self):
        fake = FakeClusterStore(records=[record("c1", status="alerted"), record("c2", status="normal")])
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=fake, cluster_id="c1")
        result = executor.run("list_active_clusters", {"status": "alerted"})
        assert [c["cluster_id"] for c in result["clusters"]] == ["c1"]

    def test_search_related_logs_chi_tra_field_can_thiet_va_cat_stack_trace(self):
        """Khong nhoi nguyen log document vao message role=tool: phinh token
        lam cham vong goi model tiep theo (xem tools._log_summary)."""
        write("log-1", stack_trace="X" * 2000, metadata={"user_id": "u1"})
        executor = assistant_tools.ToolExecutor(store=main.store, cluster_store=None, cluster_id="c1")

        row = executor.run("search_related_logs", {})["results"][0]

        assert set(row) <= {"timestamp", "service", "level", "message", "trace_id", "stack_trace"}
        assert len(row["stack_trace"]) == assistant_tools.MAX_STACK_TRACE_CHARS

    def test_get_trace_bi_tat_khi_chua_cau_hinh_jaeger(self, monkeypatch):
        monkeypatch.setattr(assistant_config, "JAEGER_QUERY_URL", "")
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=None, cluster_id="c1")

        assert executor.run("get_trace", {"trace_id": "a" * 32}) == {"error": "jaeger is not configured"}
        assert "get_trace" not in [t["function"]["name"] for t in assistant_tools.tool_schemas()]

    def test_get_trace_duoc_chao_cho_model_khi_da_cau_hinh_jaeger(self, monkeypatch):
        monkeypatch.setattr(assistant_config, "JAEGER_QUERY_URL", "http://jaeger:16686/jaeger")
        assert "get_trace" in [t["function"]["name"] for t in assistant_tools.tool_schemas()]

    def test_get_trace_tu_choi_trace_id_sai_dinh_dang_truoc_khi_goi_jaeger(self, monkeypatch):
        monkeypatch.setattr(assistant_config, "JAEGER_QUERY_URL", "http://jaeger:16686/jaeger")
        monkeypatch.setattr(assistant_tools.httpx, "get", lambda *a, **kw: pytest.fail("da goi Jaeger"))
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=None, cluster_id="c1")

        result = executor.run("get_trace", {"trace_id": "../../secret"})

        assert result["error"].startswith("trace_id must be")

    def test_get_trace_404_noi_ro_jaeger_luu_trong_ram(self, monkeypatch):
        monkeypatch.setattr(assistant_config, "JAEGER_QUERY_URL", "http://jaeger:16686/jaeger")
        monkeypatch.setattr(assistant_tools.httpx, "get",
                            lambda *a, **kw: FakeJaegerResponse(status_code=404))
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=None, cluster_id="c1")

        result = executor.run("get_trace", {"trace_id": "b" * 32})

        assert result["error"] == "trace not found"
        assert "RAM" in result["hint"]

    def test_get_trace_tom_tat_span_theo_thu_tu_thoi_gian_va_giu_base_path(self, monkeypatch):
        monkeypatch.setattr(assistant_config, "JAEGER_QUERY_URL", "http://jaeger:16686/jaeger")
        called = {}
        payload = jaeger_trace(span_count=2)
        payload["data"][0]["spans"][0]["tags"] = [
            {"key": "error", "value": True}, {"key": "http.status_code", "value": 500},
        ]

        def fake_get(url, **kwargs):
            called["url"] = url
            return FakeJaegerResponse(payload=payload)

        monkeypatch.setattr(assistant_tools.httpx, "get", fake_get)
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=None, cluster_id="c1")

        result = executor.run("get_trace", {"trace_id": "a" * 32})

        assert called["url"] == f"http://jaeger:16686/jaeger/api/traces/{'a' * 32}"
        assert result["span_count"] == 2
        assert [span["operation"] for span in result["spans"]] == ["GET /step-1", "GET /step-0"]
        assert result["spans"][1] == {
            "service": "demo-web", "operation": "GET /step-0", "duration_ms": 2.0,
            "error": True, "http_status": 500,
        }
        assert "error" not in result["spans"][0]

    def test_get_trace_cat_bot_span_de_khong_phinh_token(self, monkeypatch):
        monkeypatch.setattr(assistant_config, "JAEGER_QUERY_URL", "http://jaeger:16686")
        monkeypatch.setattr(assistant_tools.httpx, "get", lambda *a, **kw: FakeJaegerResponse(
            payload=jaeger_trace(span_count=assistant_tools.MAX_TRACE_SPANS + 10)))
        executor = assistant_tools.ToolExecutor(store=None, cluster_store=None, cluster_id="c1")

        result = executor.run("get_trace", {"trace_id": "c" * 32})

        assert result["span_count"] == assistant_tools.MAX_TRACE_SPANS + 10
        assert len(result["spans"]) == assistant_tools.MAX_TRACE_SPANS

    def test_loi_trong_tool_duoc_boc_thanh_error_khong_lam_vo_chat(self):
        class BoomStore:
            def search_with_total(self, **_kw):
                raise RuntimeError("storage that bai")

        executor = assistant_tools.ToolExecutor(store=BoomStore(), cluster_store=None, cluster_id="c1")
        result = executor.run("search_related_logs", {})
        assert result["error"] == "RuntimeError: storage that bai"


# --------------------------------------------------------------------------- gioi han lich su hoi thoai

class TestTrimHistory:
    """_trim_history chi cat phan GUI len model; hoi thoai van luu day du."""

    def user(self, text):
        return {"role": "user", "content": text, "created_at": "x"}

    def assistant(self, text):
        return {"role": "assistant", "content": text, "created_at": "x"}

    def test_ngan_hon_gioi_han_thi_giu_nguyen(self):
        history = [self.user("1"), self.assistant("2")]
        assert assistant_service._trim_history(history, 20) == history

    def test_cat_bot_phan_cu_khi_vuot_gioi_han(self):
        history = [self.user(str(i)) for i in range(10)]
        trimmed = assistant_service._trim_history(history, 4)
        assert [m["content"] for m in trimmed] == ["6", "7", "8", "9"]

    def test_bo_tool_message_mo_coi_o_dau_sau_khi_cat(self):
        """Cat ngang chuoi tool_calls -> OpenAI tra 400 vi message `tool`
        khong con assistant/tool_calls sinh ra no dung truoc."""
        history = [
            self.user("cu"),
            {"role": "assistant", "content": None, "created_at": "x",
             "tool_calls": [{"id": "call_1", "name": "get_cluster_history", "arguments": "{}"}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "get_cluster_history",
             "content": "{}", "created_at": "x"},
            self.assistant("tra loi cu"),
            self.user("moi"),
        ]
        # limit=3 cat ra [tool, assistant, user] - tool dau tien la mo coi.
        trimmed = assistant_service._trim_history(history, 3)
        assert [m["role"] for m in trimmed] == ["user"]
        assert trimmed[0]["content"] == "moi"

    def test_khong_con_message_user_nao_thi_bo_het_ngu_canh(self):
        history = [self.assistant("a"), self.assistant("b"), self.assistant("c")]
        assert assistant_service._trim_history(history, 2) == []

    def test_run_chat_turn_chi_gui_phan_lich_su_da_cat(self, clusters, conversations,
                                                       azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        monkeypatch.setattr(assistant_config, "MAX_HISTORY_MESSAGES", 2)
        conversations.docs["c1"] = {
            "cluster_id": "c1", "created_at": "x", "updated_at": "x",
            "messages": [self.user(f"cu {i}") for i in range(6)],
        }
        holder = patch_openai(monkeypatch, [fake_response(fake_message(content="xong"))])

        resp = client.post("/assistant/clusters/c1/conversation/messages", json={"message": "moi"})

        assert resp.status_code == 200
        # FakeOpenAI giu THAM CHIEU toi chinh list openai_messages, ma list do
        # con duoc append cau tra loi sau khi goi -> chi kiem phan dau (4 phan
        # tu da gui luc goi), khong so sanh ca list.
        sent = holder["instance"].calls[0]["messages"]
        # system + 2 message cu gan nhat + user moi (khong phai ca 6 cai cu)
        assert [m["role"] for m in sent[:4]] == ["system", "user", "user", "user"]
        assert [m["content"] for m in sent[1:4]] == ["cu 4", "cu 5", "moi"]
        assert all(m.get("content") != "cu 0" for m in sent)
        # Nhung LUU thi van day du: 6 cu + user moi + tra loi cua assistant.
        assert len(conversations.docs["c1"]["messages"]) == 8


# --------------------------------------------------------------------------- hieu nang 1 luot chat

class TestHieuNang:
    """Chong hoi quy cac toi uu do tre cua 1 luot chat - moi test o day gan
    voi MOT chi phi thua da do duoc tren duong di cua POST .../messages."""

    def post(self, message="hi"):
        return client.post("/assistant/clusters/c1/conversation/messages", json={"message": message})

    def test_dung_lai_client_openai_giua_cac_request(self, clusters, conversations,
                                                     azure_openai_env, monkeypatch):
        """Moi lan khoi tao OpenAI(...) la 1 connection pool + bat tay TLS moi."""
        clusters.records = [record("c1")]
        created = []

        def factory(*, api_key=None, base_url=None, timeout=None):
            fake = FakeOpenAI(
                [fake_response(fake_message(content="A")), fake_response(fake_message(content="B"))],
                api_key=api_key, base_url=base_url, timeout=timeout,
            )
            created.append(fake)
            return fake

        monkeypatch.setattr(assistant_service, "OpenAI", factory)

        assert self.post("cau 1").status_code == 200
        assert self.post("cau 2").status_code == 200

        assert len(created) == 1  # 2 request, chi 1 lan khoi tao client
        assert len(created[0].calls) == 2

    def test_chi_doc_5_log_mau_cho_system_prompt(self, clusters, conversations,
                                                 azure_openai_env, monkeypatch):
        """system prompt chi nhung 5 log mau - doc 20 doc day du la doc thua."""
        clusters.records = [record("c1", log_ids=[f"log-{i}" for i in range(20)])]
        for index in range(20):
            write(f"log-{index}")
        seen = {}
        original = main.store.get_logs

        def spy(log_ids):
            seen["ids"] = list(log_ids)
            return original(log_ids)

        monkeypatch.setattr(main.store, "get_logs", spy)
        patch_openai(monkeypatch, [fake_response(fake_message(content="xong"))])

        assert self.post().status_code == 200
        assert len(seen["ids"]) == 5

    def test_vong_cuoi_khong_gui_tools(self, clusters, conversations, azure_openai_env, monkeypatch):
        """Con tools o vong cuoi thi model co the lai doi tra cuu va het luot ma
        chua tra loi - mat 1 lan goi model chi de nhan cau "da dat gioi han"."""
        clusters.records = [record("c1")]
        clusters.history = [{"cluster_id": "c1", "score": 1.0, "status": "normal",
                             "recorded_at": "2026-10-29T00:00:00+00:00"}]
        holder = patch_openai(monkeypatch, [
            fake_response(fake_message(
                content=None, tool_calls=[_FakeToolCall("call_1", "get_cluster_history", "{}")])),
            fake_response(fake_message(content="Score dang tang dan.")),
        ])

        assert self.post("Xu huong the nao?").status_code == 200

        calls = holder["instance"].calls
        assert "tools" in calls[0]
        assert "tools" not in calls[-1]

    def test_system_prompt_cat_stack_trace(self, clusters, conversations,
                                           azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        write("log-1", stack_trace="Y" * 2000)
        holder = patch_openai(monkeypatch, [fake_response(fake_message(content="xong"))])

        assert self.post().status_code == 200

        system_prompt = holder["instance"].calls[0]["messages"][0]["content"]
        cut = assistant_tools.MAX_STACK_TRACE_CHARS
        assert "Y" * cut in system_prompt
        assert "Y" * (cut + 1) not in system_prompt


# --------------------------------------------------------------------------- GET /assistant/health

class TestAssistantHealth:
    """Endpoint cong khai cho trang "Trang thai he thong" - luon HTTP 200,
    khong goi Azure OpenAI that (poll 15s/lan)."""

    def test_khong_can_token_va_luon_tra_200(self, clusters, conversations, azure_openai_env):
        original = client.headers.copy()
        client.headers.pop("Authorization", None)
        try:
            response = client.get("/assistant/health")
        finally:
            client.headers = original
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_thieu_cau_hinh_bao_chua_cau_hinh(self, clusters, conversations, monkeypatch):
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        body = client.get("/assistant/health").json()
        assert body["status"] == "chưa cấu hình"

    def test_kho_hoi_thoai_chua_san_sang(self, clusters, azure_openai_env):
        original = main.app.state.assistant_conversations
        main.app.state.assistant_conversations = None
        try:
            body = client.get("/assistant/health").json()
        finally:
            main.app.state.assistant_conversations = original
        assert body["status"] == "kho hội thoại chưa sẵn sàng"

    def test_bao_loi_cua_lan_goi_azure_gan_nhat(self, clusters, conversations, azure_openai_env,
                                                monkeypatch):
        clusters.records = [record("c1")]

        def boom(*, api_key=None, base_url=None, timeout=None):
            class Boom:
                def __init__(self):
                    self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

                def _create(self, **_kw):
                    raise PermissionError("unsupported_country_region_territory")

            return Boom()

        monkeypatch.setattr(assistant_service, "OpenAI", boom)
        assert client.post("/assistant/clusters/c1/conversation/messages",
                           json={"message": "hi"}).status_code == 502

        body = client.get("/assistant/health").json()
        assert body["status"] == "lỗi gọi gần nhất: PermissionError"
        assert body["last_call_at"] is not None


# --------------------------------------------------------------------------- SSE tren chinh endpoint cu
# DAT O CUOI FILE co y: test loi o day ghi _last_call = that bai, ma
# TestAssistantHealth phia tren doc dung gia tri do (xem service._record_call).

def fake_chunk(content=None, tool_calls=None):
    return SimpleNamespace(choices=[
        SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls)),
    ])


def fake_tool_call_delta(index, id_=None, name=None, arguments=None):
    """1 manh tool_call trong stream - id/name o chunk dau, arguments noi dan."""
    return SimpleNamespace(index=index, id=id_,
                           function=SimpleNamespace(name=name, arguments=arguments))


def patch_openai_stream(monkeypatch, chunk_batches):
    """Fake client cho che do stream=True: moi lan goi tra ve 1 list chunk."""
    batches = list(chunk_batches)
    calls: list[dict] = []

    def factory(*, api_key=None, base_url=None, timeout=None):
        def create(**kwargs):
            calls.append(kwargs)
            return iter(batches.pop(0))

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(assistant_service, "OpenAI", factory)
    return calls


class TestStreamingSSE:
    """CUNG endpoint POST .../messages, chon dang tra ve theo header Accept."""

    def post_stream(self, message="hi"):
        return client.post("/assistant/clusters/c1/conversation/messages",
                           json={"message": message},
                           headers={"Accept": "text/event-stream"})

    def events(self, response):
        return [json.loads(line[len("data: "):])
                for line in response.text.splitlines() if line.startswith("data: ")]

    def test_day_tung_doan_chu_roi_gui_ca_hoi_thoai_o_cuoi(self, clusters, conversations,
                                                           azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        patch_openai_stream(monkeypatch, [[fake_chunk("Nguyen "), fake_chunk("nhan: X"), fake_chunk()]])

        resp = self.post_stream("Loi nay la gi?")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = self.events(resp)
        assert [e["delta"] for e in events if "delta" in e] == ["Nguyen ", "nhan: X"]
        conversation = events[-1]["conversation"]
        assert [m["role"] for m in conversation["messages"]] == ["user", "assistant"]
        assert conversation["messages"][1]["content"] == "Nguyen nhan: X"
        # Hoi thoai phai duoc LUU truoc khi gui event cuoi - F5 lai van thay.
        assert conversations.docs["c1"]["messages"] == conversation["messages"]

    def test_bao_ten_tool_dang_tra_cuu_truoc_khi_tra_loi(self, clusters, conversations,
                                                         azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        clusters.history = [{"cluster_id": "c1", "score": 1.0, "status": "normal",
                             "recorded_at": "2026-10-29T00:00:00+00:00"}]
        calls = patch_openai_stream(monkeypatch, [
            [fake_chunk(tool_calls=[fake_tool_call_delta(0, id_="call_1",
                                                         name="get_cluster_history")]),
             fake_chunk(tool_calls=[fake_tool_call_delta(0, arguments="{}")])],
            [fake_chunk("Score dang tang dan.")],
        ])

        resp = self.post_stream("Xu huong the nao?")

        events = self.events(resp)
        assert [e["tool"] for e in events if "tool" in e] == ["get_cluster_history"]
        messages = events[-1]["conversation"]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
        assert "recorded_at" in messages[2]["content"]
        assert all(call.get("stream") is True for call in calls)

    def test_khong_gui_accept_thi_van_tra_json_nhu_cu(self, clusters, conversations,
                                                      azure_openai_env, monkeypatch):
        clusters.records = [record("c1")]
        calls = patch_openai_stream(monkeypatch, [[fake_chunk("khong dung den")]])
        patch_openai(monkeypatch, [fake_response(fake_message(content="tra loi JSON"))])

        resp = client.post("/assistant/clusters/c1/conversation/messages", json={"message": "hi"})

        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["messages"][1]["content"] == "tra loi JSON"
        assert calls == []  # nhanh JSON KHONG truyen stream=True

    def test_loi_giua_stream_bao_bang_event_error(self, clusters, conversations,
                                                  azure_openai_env, monkeypatch):
        """Header 200 da gui roi nen khong the doi thanh 502 - bao bang event."""
        clusters.records = [record("c1")]

        def factory(*, api_key=None, base_url=None, timeout=None):
            def create(**_kwargs):
                raise PermissionError("unsupported_country_region_territory")

            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        monkeypatch.setattr(assistant_service, "OpenAI", factory)

        resp = self.post_stream()

        assert resp.status_code == 200
        assert self.events(resp)[-1]["error"] == "AI Assistant loi: PermissionError"
        assert conversations.docs == {}  # khong luu hoi thoai nua voi

    def test_cum_khong_ton_tai_van_la_404_that(self, clusters, conversations, azure_openai_env):
        """Loi TRUOC khi stream bat dau van la HTTP status that, khong phai event."""
        resp = client.post("/assistant/clusters/khong-co/conversation/messages",
                           json={"message": "hi"}, headers={"Accept": "text/event-stream"})
        assert resp.status_code == 404
