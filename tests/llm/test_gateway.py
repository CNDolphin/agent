import json

import httpx
import pytest
import respx

from mhagent.auth_session import AuthSession, TokenPair
from mhagent.llm.base import AuthExpired, DuplicateRequest, GatewayUnavailable, InsufficientCredits
from mhagent.llm.gateway import CodeInvalid, GatewayClient, InvalidPhone, TooFrequent
from mhagent.store.db import LocalStore

BASE = "http://gw.local"


@pytest.fixture
def client(tmp_path):
    store = LocalStore(tmp_path, "pw")
    session = AuthSession(store)
    session.save(TokenPair(access_token="access-1", refresh_token="refresh-1", expires_in=3600))
    gateway = GatewayClient(BASE, session)
    yield gateway
    gateway.close()
    store.close()


def _json(**kwargs):
    return httpx.Response(200, json=kwargs)


def test_send_code_and_local_validation(client):
    with respx.mock:
        route = respx.post(f"{BASE}/auth/sms/send").mock(return_value=httpx.Response(204))
        client.send_code("13800000000")
        assert route.call_count == 1
        assert json.loads(route.calls[0].request.content) == {"phone": "13800000000"}
    with pytest.raises(InvalidPhone):
        client.send_code("12345")


def test_login_saves_tokens_and_errors(client, tmp_path):
    with respx.mock:
        respx.post(f"{BASE}/auth/login").mock(
            return_value=_json(access_token="a2", refresh_token="r2", expires_in=600, is_new=True)
        )
        tokens = client.login("13800000000", "123456")
    assert tokens.is_new is True
    assert client.session.load().access_token == "a2"

    with respx.mock:
        respx.post(f"{BASE}/auth/login").mock(
            return_value=httpx.Response(401, json={"code": 40102, "message": "bad"})
        )
        with pytest.raises(CodeInvalid):
            client.login("13800000000", "000000")

    with respx.mock:
        respx.post(f"{BASE}/auth/sms/send").mock(
            return_value=httpx.Response(429, json={"code": 42901}, headers={"Retry-After": "30"})
        )
        with pytest.raises(TooFrequent) as exc:
            client.send_code("13800000000")
    assert exc.value.wait_seconds == 30


def test_chat_success_headers_and_body(client):
    with respx.mock:
        route = respx.post(f"{BASE}/llm/chat").mock(
            return_value=_json(
                content="你好",
                usage={"input_hit": 10, "input_miss": 20, "output": 5},
                cost=3,
                balance=97,
                low_balance=True,
            )
        )
        result = client.chat([{"role": "user", "content": "hi"}])
    assert result.content == "你好"
    assert (result.input_hit, result.input_miss, result.output) == (10, 20, 5)
    assert (result.cost, result.balance, result.low_balance) == (3, 97, True)
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer access-1"
    assert request.headers["x-request-id"]
    body = json.loads(request.content)
    assert set(body) == {"model", "messages", "max_tokens", "stream"}
    assert "thinking" not in body


def test_insufficient_credits(client):
    with respx.mock:
        respx.post(f"{BASE}/llm/chat").mock(
            return_value=httpx.Response(402, json={"code": 40201, "message": "no credits"})
        )
        with pytest.raises(InsufficientCredits):
            client.chat([{"role": "user", "content": "hi"}])


def test_refresh_retry_once(client):
    with respx.mock:
        chat = respx.post(f"{BASE}/llm/chat").mock(
            side_effect=[
                httpx.Response(401, json={"code": 40101}),
                _json(content="ok", usage={}, cost=1, balance=9),
            ]
        )
        refresh = respx.post(f"{BASE}/auth/refresh").mock(
            return_value=_json(access_token="access-2", refresh_token="refresh-2", expires_in=600)
        )
        result = client.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert chat.call_count == 2
    assert refresh.call_count == 1
    first_id = chat.calls[0].request.headers["x-request-id"]
    second_id = chat.calls[1].request.headers["x-request-id"]
    assert first_id == second_id
    assert client.session.load().access_token == "access-2"


def test_refresh_failure_raises_auth_expired(client):
    with respx.mock:
        respx.post(f"{BASE}/llm/chat").mock(return_value=httpx.Response(401, json={"code": 40101}))
        respx.post(f"{BASE}/auth/refresh").mock(return_value=httpx.Response(401, json={"code": 40101}))
        with pytest.raises(AuthExpired):
            client.chat([{"role": "user", "content": "hi"}])


def test_502_retried_once_with_same_request_id(client):
    with respx.mock:
        route = respx.post(f"{BASE}/llm/chat").mock(
            side_effect=[
                httpx.Response(502, json={"code": 50201}),
                httpx.Response(502, json={"code": 50201}),
            ]
        )
        with pytest.raises(GatewayUnavailable):
            client.chat([{"role": "user", "content": "hi"}])
    assert route.call_count == 2
    reqs = [c.request for c in route.calls]
    assert reqs[0].headers["x-request-id"] == reqs[1].headers["x-request-id"]


def test_timeout_retried_once(client):
    calls = {"n": 0}

    def boom(request):
        calls["n"] += 1
        raise httpx.ConnectTimeout("timeout")

    with respx.mock:
        respx.post(f"{BASE}/llm/chat").mock(side_effect=boom)
        with pytest.raises(GatewayUnavailable):
            client.chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 2


def test_duplicate_request(client):
    with respx.mock:
        respx.post(f"{BASE}/llm/chat").mock(
            return_value=httpx.Response(409, json={"code": 40901, "message": "dup", "cost": 7})
        )
        with pytest.raises(DuplicateRequest) as exc:
            client.chat([{"role": "user", "content": "hi"}])
    assert exc.value.cost == 7


def test_stream_success(client):
    body = (
        'event: delta\ndata: {"text": "你"}\n\n'
        'event: delta\ndata: {"text": "好"}\n\n'
        'event: done\ndata: {"usage": {"input_hit": 1, "input_miss": 2, "output": 3}, '
        '"cost": 1, "balance": 99}\n\n'
    )
    with respx.mock:
        respx.post(f"{BASE}/llm/chat").mock(
            return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        )
        chunks = list(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert "".join(chunks) == "你好"
    assert client.last_stream_result.output == 3
    assert client.last_stream_result.balance == 99


def test_stream_error_event(client):
    body = 'event: delta\ndata: {"text": "你"}\n\nevent: error\ndata: {"code": 50201, "message": "boom"}\n\n'
    with respx.mock:
        respx.post(f"{BASE}/llm/chat").mock(
            return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        )
        with pytest.raises(GatewayUnavailable):
            list(client.chat_stream([{"role": "user", "content": "hi"}]))


def test_token_not_written_in_plaintext(tmp_path):
    store = LocalStore(tmp_path, "pw")
    session = AuthSession(store)
    session.save(TokenPair(access_token="TOKEN-MARKER-xyz", refresh_token="REFRESH-MARKER-xyz"))
    store.close()
    for path in tmp_path.iterdir():
        if path.is_file():
            assert b"TOKEN-MARKER-xyz" not in path.read_bytes()
            assert b"REFRESH-MARKER-xyz" not in path.read_bytes()


def test_list_pending_reports_and_download(client):
    with respx.mock:
        respx.get(f"{BASE}/reports/pending").mock(
            return_value=_json(
                items=[{"report_id": 3, "version": 2, "filename": "报告.pdf", "title": "测评"}]
            )
        )
        route = respx.get(f"{BASE}/reports/3/download").mock(
            return_value=httpx.Response(
                200,
                content=b"%PDF-1.4",
                headers={
                    "content-type": "application/pdf",
                    "content-disposition": "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf",
                },
            )
        )
        items = client.list_pending_reports()
        name, content, content_type = client.download_report(3)

    assert items == [{"report_id": 3, "version": 2, "filename": "报告.pdf", "title": "测评"}]
    assert name == "报告.pdf"
    assert content == b"%PDF-1.4"
    assert content_type == "application/pdf"
    assert route.call_count == 1


def test_mark_report_read_accepts_204(client):
    with respx.mock:
        route = respx.post(f"{BASE}/reports/3/read").mock(return_value=httpx.Response(204))
        client.mark_report_read(3)
    assert route.call_count == 1


def test_stream_report_events(client):
    body = (
        "id: 3:1\n"
        "event: report.created\n"
        'data: {"report_id": 3, "version": 1}\n\n'
    )
    with respx.mock:
        respx.get(f"{BASE}/notifications/stream").mock(
            return_value=httpx.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )
        )
        events = list(client.stream_report_events())
    assert events == [{"event": "report.created", "data": {"report_id": 3, "version": 1}}]
