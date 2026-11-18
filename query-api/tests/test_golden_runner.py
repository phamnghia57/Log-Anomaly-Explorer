import importlib.util
import json
import pathlib

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "golden_runner", pathlib.Path(__file__).parent / "golden" / "run_assistant_golden.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def conversation(answer="Nguyen nhan: downstream 502."):
    return {"cluster_id": "c1", "messages": [
        {"role": "user", "content": "Loi nay do dau?"},
        {"role": "assistant", "content": answer},
    ]}


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def questions(count=2):
    return [{"id": f"q{i}", "cluster_id": f"c{i}", "question": f"cau {i}", "expected": "x"}
            for i in range(count)]


class TestLoadQuestions:
    def write(self, tmp_path, data):
        path = tmp_path / "questions.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_doc_duoc_file_hop_le(self, tmp_path):
        assert len(runner.load_questions(self.write(tmp_path, questions(3)))) == 3

    def test_tu_choi_khi_thieu_truong(self, tmp_path):
        path = self.write(tmp_path, [{"id": "q1", "question": "thieu cluster_id"}])
        with pytest.raises(ValueError, match="cluster_id"):
            runner.load_questions(path)

    def test_tu_choi_id_trung(self, tmp_path):
        path = self.write(tmp_path, [
            {"id": "q1", "cluster_id": "c1", "question": "a"},
            {"id": "q1", "cluster_id": "c2", "question": "b"},
        ])
        with pytest.raises(ValueError, match="trung"):
            runner.load_questions(path)

    def test_tu_choi_danh_sach_rong(self, tmp_path):
        with pytest.raises(ValueError):
            runner.load_questions(self.write(tmp_path, []))


class TestRun:
    def test_lay_cau_tra_loi_cuoi_cung_cua_assistant(self):
        with client_for(lambda request: httpx.Response(200, json=conversation())) as client:
            rows = runner.run(client, questions(1), token="t", reset=False)

        assert rows[0]["answer"] == "Nguyen nhan: downstream 502."
        assert rows[0]["error"] == ""
        assert rows[0]["asked_at"].endswith("+00:00")

    def test_xoa_hoi_thoai_truoc_moi_cau(self):
        deleted = []

        def handler(request):
            if request.method == "DELETE":
                deleted.append(str(request.url))
                return httpx.Response(200, json={"result": "deleted"})
            return httpx.Response(200, json=conversation())

        with client_for(handler) as client:
            runner.run(client, questions(2), token="t")

        assert [url.rsplit("/", 1)[-1] for url in deleted] == ["c0", "c1"]

    def test_keep_history_thi_khong_xoa(self):
        seen = []

        def handler(request):
            seen.append(request.method)
            return httpx.Response(200, json=conversation())

        with client_for(handler) as client:
            runner.run(client, questions(2), token="t", reset=False)

        assert "DELETE" not in seen

    def test_mot_cau_loi_khong_lam_hong_ca_luot_do(self):
        def handler(request):
            if "c0" in str(request.url):
                return httpx.Response(502, json={"detail": "AI Assistant loi: RateLimitError"})
            return httpx.Response(200, json=conversation())

        with client_for(handler) as client:
            rows = runner.run(client, questions(2), token="t", reset=False)

        assert len(rows) == 2
        assert "HTTPStatusError" in rows[0]["error"]
        assert rows[0]["answer"] == ""
        assert rows[1]["error"] == ""

    def test_gui_kem_bearer_token(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=conversation())

        with client_for(handler) as client:
            runner.run(client, questions(1), token="abc", reset=False)

        assert seen["auth"] == "Bearer abc"


class TestLogin:
    def test_gui_header_csrf_va_tra_token(self):
        seen = {}

        def handler(request):
            seen["csrf"] = request.headers.get("x-csrf-protection")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"token": "jwt-123"})

        with client_for(handler) as client:
            assert runner.login(client, "admin", "pass") == "jwt-123"

        assert seen["csrf"] == "1"
        assert seen["body"] == {"username": "admin", "password": "pass"}


def test_csv_giu_du_cot_de_cham_diem(tmp_path):
    with client_for(lambda request: httpx.Response(200, json=conversation())) as client:
        rows = runner.run(client, questions(1), token="t", reset=False)

    output = tmp_path / "scores.csv"
    runner.write_csv(rows, str(output))
    lines = output.read_text(encoding="utf-8").splitlines()

    assert lines[0].split(",") == runner.FIELDS
    assert len(lines) == 2


@pytest.mark.parametrize("cluster_id", [None, "", " ", 123, [], " c1", "c1 ",
                                       "DOI-THANH-CLUSTER-ID-THAT", "placeholder-id"])
def test_unbound_id_rejected_before_any_http(cluster_id):
    data = [{**questions(1)[0], "cluster_id": cluster_id}]
    with client_for(lambda request: pytest.fail("unbound ID must not call HTTP")) as client:
        with pytest.raises(ValueError, match="cluster_id"):
            runner.run(client, data, token="t")


@pytest.mark.parametrize("data", [[None], ["question"], [{}],
                                 [{"id": [], "cluster_id": "c1", "question": "q"}],
                                 [{"id": "q1", "cluster_id": "c1", "question": " "}]])
def test_malformed_questions_report_value_error(data):
    with pytest.raises(ValueError):
        runner.validate_questions(data)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_failed_reset_does_not_call_model_and_keeps_later_rows(status):
    asked = []

    def handler(request):
        if request.method == "DELETE":
            return httpx.Response(status if request.url.path.endswith("c0") else 200)
        asked.append(request.url.path)
        return httpx.Response(200, json=conversation())

    with client_for(handler) as client:
        rows = runner.run(client, questions(2), token="t")
    assert len(rows) == 2
    assert "HTTPStatusError" in rows[0]["error"]
    assert rows[0]["answer"] == rows[0]["latency_s"] == ""
    assert rows[1]["error"] == ""
    assert len(asked) == 1 and "/c1/" in asked[0]


def test_reset_404_is_empty_history_and_expected_is_not_sent_to_model():
    bodies = []

    def handler(request):
        if request.method == "DELETE":
            return httpx.Response(404)
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=conversation())

    with client_for(handler) as client:
        rows = runner.run(client, questions(1), token="t")
    assert bodies == [{"message": "cau 0"}]
    assert rows[0]["expected"] == "x"
    assert not rows[0]["error"]


def test_reset_network_error_is_recorded():
    def handler(request):
        assert request.method == "DELETE"
        raise httpx.ConnectError("reset unavailable", request=request)

    with client_for(handler) as client:
        rows = runner.run(client, questions(1), token="t")
    assert "ConnectError" in rows[0]["error"] and not rows[0]["answer"]
