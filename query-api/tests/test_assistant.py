"""Test cho AI Assistant: chat loop (tool calling), persistence qua
ConversationRepository gia, va endpoint /assistant/*.

Khong goi OpenAI/Langfuse that: mock lop client (OpenAI tu service.py goi)
de kiem soat kich ban (tra loi thang, hoac goi tool truoc khi tra loi).
Dung STORAGE_BACKEND=memory (xem conftest.py) nen khong can OpenSearch that -
cluster_store/assistant_conversations trong app.state duoc thay bang fake.
"""

from __future__ import annotations

import importlib
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

    def test_loi_trong_tool_duoc_boc_thanh_error_khong_lam_vo_chat(self):
        class BoomStore:
            def search_with_total(self, **_kw):
                raise RuntimeError("storage that bai")

        executor = assistant_tools.ToolExecutor(store=BoomStore(), cluster_store=None, cluster_id="c1")
        result = executor.run("search_related_logs", {})
        assert result["error"] == "RuntimeError: storage that bai"
