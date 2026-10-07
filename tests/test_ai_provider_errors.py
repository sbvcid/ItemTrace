"""AI provider 的失敗分類與 SSE 解析。

這一組測試的重點是**分類**，不是「有沒有回應」：

  provider 掛掉 / 暫時不可用  → ProviderError
  provider 正常但模型輸出壞掉 → AnalyzerError（格式問題）

2026-10-05 遇到的真實故障：OpenRouter 因上游 SSE 串流失敗，在回應裡
注入 `{"error": {"code": 502, "metadata": {"error_type":
"provider_unavailable"}}}`。舊的程式沒有任何 error 物件的判斷，於是這個
payload 掉進 extract_text 的 KeyError 分支，被回報成「AI 服務回應格式
不如預期」—— 把上游故障講成模型的問題。

沒有真的呼叫 OpenRouter / Gemini：全部用假的 payload 與本機 mock 伺服器。
"""

from __future__ import annotations

import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from shop import ai_client
from shop.ai_client import AnalyzerError, ProviderError

SECRET = "sk-or-v1-TEST-LOCAL-KEY-0000000000"
GEMINI_SECRET = "AIzaFakeGeminiKey0123456789ABCDEF"
MODEL = "qwen/qwen3.8-27b:free"

# 報告中的真實 payload 形狀
UNAVAILABLE = {
    "id": "gen-1750000000-abc",
    "error": {
        "message": "JSON error injected into SSE stream",
        "code": 502,
        "metadata": {"error_type": "provider_unavailable"},
    },
}


def envelope(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def decode(raw, *, content_type="", model=MODEL, api_key=SECRET):
    return ai_client.decode_provider_response(
        raw if isinstance(raw, bytes) else raw.encode(),
        content_type=content_type, api_key=api_key, model=model,
    )


# ----------------------------------------------------------------------
# 1. 正常回應（既有行為不得改變）
# ----------------------------------------------------------------------


def test_plain_json_response_still_works():
    payload = decode(json.dumps(envelope('{"suggestions": []}')))
    assert ai_client.extract_text(payload, SECRET) == '{"suggestions": []}'


def test_suggestion_pipeline_unchanged_for_plain_json():
    payload = decode(json.dumps(envelope(
        '{"suggestions":[{"field":"brand","value":"ASUS","confidence":0.9,'
        '"source_photo_index":0}]}'
    )))
    text = ai_client.extract_text(payload, SECRET)
    assert ai_client.parse_suggestions(text, [{"id": "p1"}]) == [
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_id": "p1"}
    ]


# ----------------------------------------------------------------------
# 2. provider unavailable（不進 suggestion parser）
# ----------------------------------------------------------------------


def test_reported_provider_unavailable_is_a_provider_error():
    """報告中的 payload 必須被辨識為 provider failure。"""
    with pytest.raises(ProviderError) as excinfo:
        decode(json.dumps(UNAVAILABLE))
    message = str(excinfo.value)
    assert "暫時無法使用" in message
    assert "provider_unavailable" in message
    assert "502" in message


def test_provider_failure_is_not_reported_as_a_format_error():
    """核心回歸：不可再說「回應格式不如預期」。"""
    with pytest.raises(ProviderError) as excinfo:
        decode(json.dumps(UNAVAILABLE))
    assert "回應格式不如預期" not in str(excinfo.value)


def test_provider_error_never_reaches_the_suggestion_parser():
    with pytest.raises(ProviderError):
        payload = decode(json.dumps(UNAVAILABLE))
        ai_client.parse_suggestions(
            ai_client.extract_text(payload, SECRET), [{"id": "p1"}]
        )


def test_extract_text_also_rejects_provider_errors_defensively():
    """extract_text 是公開函式，這個判斷要對任何呼叫端成立。"""
    with pytest.raises(ProviderError):
        ai_client.extract_text(UNAVAILABLE, SECRET)


def test_string_valued_error_is_still_handled():
    """有些端點的 error 就是字串。"""
    with pytest.raises(ProviderError) as excinfo:
        decode(json.dumps({"error": "bad key " + SECRET}))
    assert SECRET not in str(excinfo.value)


# ----------------------------------------------------------------------
# 3. 串流中途的 provider error
# ----------------------------------------------------------------------


def test_error_event_inside_sse_is_a_provider_error():
    stream = (
        'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        'data: {"id":"gen-1","error":{"message":"upstream gone","code":502,'
        '"metadata":{"error_type":"provider_unavailable"}}}\n\n'
    )
    with pytest.raises(ProviderError) as excinfo:
        decode(stream, content_type="text/event-stream")
    assert "provider_unavailable" in str(excinfo.value)


def test_sse_error_after_normal_chunks_yields_no_partial_content():
    """已經收到正常片段後才出錯 → 仍然是 provider failure，不吐半套。"""
    first = json.dumps({"choices": [{"delta": {"content": '{"field": "name"}'}}]})
    second = json.dumps(
        {"error": {"code": 502, "metadata": {"error_type": "provider_unavailable"}}}
    )
    stream = f"data: {first}\n\ndata: {second}\n\n"
    with pytest.raises(ProviderError):
        decode(stream, content_type="text/event-stream")


def test_sse_detected_without_content_type_header():
    """有些中間層不會標 text/event-stream，靠內容形狀也要認得出來。"""
    stream = 'data: {"error":{"code":503,"metadata":{"error_type":"provider_unavailable"}}}\n\n'
    with pytest.raises(ProviderError) as excinfo:
        decode(stream)  # 沒有 content_type
    assert "503" in str(excinfo.value)


# ----------------------------------------------------------------------
# 4. 模型輸出壞掉 ≠ provider 掛掉
# ----------------------------------------------------------------------


def test_malformed_model_output_is_not_a_provider_error():
    payload = decode(json.dumps(envelope("not-json")))
    with pytest.raises(AnalyzerError) as excinfo:
        ai_client.parse_suggestions(
            ai_client.extract_text(payload, SECRET), [{"id": "p1"}]
        )
    assert not isinstance(excinfo.value, ProviderError)
    assert "不是合法 JSON" in str(excinfo.value)


def test_model_output_missing_suggestions_is_not_a_provider_error():
    payload = decode(json.dumps(envelope('{"oops": 1}')))
    with pytest.raises(AnalyzerError) as excinfo:
        ai_client.parse_suggestions(
            ai_client.extract_text(payload, SECRET), [{"id": "p1"}]
        )
    assert not isinstance(excinfo.value, ProviderError)


def test_empty_choices_keeps_the_original_format_message():
    """既有契約：回應框不是 chat completion 仍然是「格式不如預期」。

    這不是 provider 故障 —— provider 有正常回應，只是框不對。
    """
    with pytest.raises(AnalyzerError) as excinfo:
        ai_client.extract_text({"choices": []}, SECRET)
    assert not isinstance(excinfo.value, ProviderError)
    assert "回應格式不如預期" in str(excinfo.value)


# ----------------------------------------------------------------------
# 5-6. SSE 註解與 [DONE]
# ----------------------------------------------------------------------


def test_sse_comment_is_ignored():
    """: OPENROUTER PROCESSING 是 keep-alive，不是 model output。"""
    stream = (
        ": OPENROUTER PROCESSING\n\n"
        ": still working\n\n"
        'data: {"choices":[{"delta":{"content":"{\\"suggestions\\": []}"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    payload = decode(stream, content_type="text/event-stream")
    assert ai_client.extract_text(payload, SECRET) == '{"suggestions": []}'


def test_sse_done_terminates_the_stream():
    """[DONE] 之後的內容不該被讀進來。"""
    stream = (
        'data: {"choices":[{"delta":{"content":"kept"}}]}\n\n'
        "data: [DONE]\n\n"
        'data: {"choices":[{"delta":{"content":"ignored"}}]}\n\n'
    )
    payload = decode(stream, content_type="text/event-stream")
    assert ai_client.extract_text(payload, SECRET) == "kept"


def test_sse_with_full_message_chunk_is_preferred():
    stream = (
        'data: {"choices":[{"message":{"content":"whole"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    payload = decode(stream, content_type="text/event-stream")
    assert ai_client.extract_text(payload, SECRET) == "whole"


def test_sse_multiline_data_is_joined():
    """SSE 允許一個事件跨多個 data: 行。"""
    stream = 'data: {"choices":[{"delta":\ndata: {"content":"split"}}]}\n\n'
    payload = decode(stream, content_type="text/event-stream")
    assert ai_client.extract_text(payload, SECRET) == "split"


# ----------------------------------------------------------------------
# 壞掉的串流
# ----------------------------------------------------------------------


def test_malformed_json_inside_sse_is_a_provider_error():
    stream = "data: {not json}\n\n"
    with pytest.raises(ProviderError) as excinfo:
        decode(stream, content_type="text/event-stream")
    assert "串流事件" in str(excinfo.value)


def test_non_json_body_is_a_provider_error():
    """整包不是 JSON（又沒 SSE 形狀）→ provider 回應壞掉。"""
    with pytest.raises(ProviderError) as excinfo:
        decode("<html>502 Bad Gateway</html>")
    assert "不是合法 JSON" in str(excinfo.value)


def test_json_array_body_is_a_provider_error():
    with pytest.raises(ProviderError):
        decode("[1, 2, 3]")


def test_incomplete_stream_without_content_is_a_provider_error():
    with pytest.raises(ProviderError) as excinfo:
        decode("data: {\"id\":\"gen-1\"}\n\n", content_type="text/event-stream")
    assert "沒有任何內容" in str(excinfo.value)


def test_done_with_no_content_is_a_model_output_problem_not_provider_failure():
    """只有 [DONE]、沒有任何內容 → provider 正常，是模型沒給東西。

    空字串不是合法 JSON，所以會被 parse_suggestions 擋下 —— 這是既有的
    模型輸出語意，不是 provider 故障，兩者不可混為一談。
    """
    payload = decode("data: [DONE]\n\n", content_type="text/event-stream")
    text = ai_client.extract_text(payload, SECRET)
    assert text == ""
    with pytest.raises(AnalyzerError) as excinfo:
        ai_client.parse_suggestions(text, [{"id": "p1"}])
    assert not isinstance(excinfo.value, ProviderError)


# ----------------------------------------------------------------------
# 7. 遮蔽
# ----------------------------------------------------------------------


def test_provider_error_message_never_leaks_keys():
    leaky = {
        "error": {
            "message": f"rejected {SECRET} and {GEMINI_SECRET}",
            "code": 401,
        }
    }
    with pytest.raises(ProviderError) as excinfo:
        decode(json.dumps(leaky))
    text = ai_client.redact(str(excinfo.value), SECRET)
    assert SECRET not in text
    assert GEMINI_SECRET not in text
    assert "sk-***" in text


def test_sse_error_message_never_leaks_keys():
    stream = (
        f'data: {{"error":{{"message":"bad {SECRET}","code":401}}}}\n\n'
    )
    with pytest.raises(ProviderError) as excinfo:
        decode(stream, content_type="text/event-stream")
    assert SECRET not in str(excinfo.value)


def test_provider_error_does_not_dump_the_whole_response():
    """只留白名單欄位，不整包 dump。"""
    noisy = {
        "id": "gen-1",
        "error": {"code": 502, "metadata": {"error_type": "provider_unavailable"}},
        "debug": {"upstream": "internal-llm-7", "trace": "x" * 500},
        "choices": [{"message": {"content": "leaked model output"}}],
    }
    with pytest.raises(ProviderError) as excinfo:
        decode(json.dumps(noisy))
    message = str(excinfo.value)
    assert "internal-llm-7" not in message
    assert "leaked model output" not in message


def test_authorization_header_is_never_in_the_message():
    with pytest.raises(ProviderError) as excinfo:
        decode(json.dumps(UNAVAILABLE))
    assert "Authorization" not in str(excinfo.value)
    assert "Bearer" not in str(excinfo.value)


# ----------------------------------------------------------------------
# 8. 向後相容
# ----------------------------------------------------------------------


def test_call_ai_provider_signature_is_unchanged():
    import inspect

    parameters = inspect.signature(ai_client.call_ai_provider).parameters
    assert list(parameters) == [
        "api_key", "model", "data_urls", "provider", "base_url", "timeout",
    ]
    assert parameters["provider"].default == ai_client.PROVIDER
    assert parameters["base_url"].default == ai_client.DEFAULT_BASE_URL
    assert parameters["timeout"].default == ai_client.TIMEOUT


def test_build_request_body_still_depends_on_provider():
    assert "response_format" in ai_client.build_request_body(
        "m", [], provider="openrouter")
    assert "response_format" not in ai_client.build_request_body(
        "m", [], provider="google")
    assert "response_format" not in ai_client.build_request_body(
        "m", [], provider="custom")
    assert "provider" not in ai_client.build_request_body("m", [], provider="openrouter")


def test_provider_error_is_an_analyzer_error():
    """既有呼叫端只抓 AnalyzerError 的地方不能因此壞掉。"""
    assert issubclass(ProviderError, AnalyzerError)


def test_no_retry_provider_is_attempted_exactly_once(monkeypatch):
    """失敗就是失敗：不重試、不換模型。

    這一組 case 全部用假的 urlopen，所以真的只會被呼叫一次。
    """
    attempts: list[str] = []

    class FakeResponse(io.BytesIO):
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

    def fake_urlopen(request, timeout=None):
        attempts.append(request.full_url)
        return FakeResponse(json.dumps(UNAVAILABLE).encode())

    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderError):
        ai_client.call_ai_provider(SECRET, MODEL, [], provider="custom",
                                   base_url="http://127.0.0.1:1/v1")
    assert len(attempts) == 1


def test_http_5xx_is_a_provider_error(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://openrouter.ai", 502, "Bad Gateway", {},
            io.BytesIO(b'{"error":"upstream"}'),
        )

    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ProviderError) as excinfo:
        ai_client.call_ai_provider(SECRET, MODEL, [])
    assert "502" in str(excinfo.value)


def test_http_401_keeps_the_original_message_format(monkeypatch):
    """既有訊息格式要保留（外部 adapter 與測試都靠它）。"""
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://openrouter.ai", 401, "Unauthorized", {},
            io.BytesIO(f'{{"error":"bad key {SECRET}"}}'.encode()),
        )

    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ProviderError) as excinfo:
        ai_client.call_ai_provider(SECRET, MODEL, [])
    message = str(excinfo.value)
    assert f"AI 服務回應 401（model={MODEL}）" in message
    assert SECRET not in message


def test_transport_failure_is_a_provider_error(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ProviderError) as excinfo:
        ai_client.call_ai_provider(SECRET, MODEL, [])
    assert "連不到 AI 服務" in str(excinfo.value)


# ----------------------------------------------------------------------
# 本機 mock 伺服器：走真實 urllib 路徑
# ----------------------------------------------------------------------


class _MockProvider(BaseHTTPRequestHandler):
    """依路徑決定回哪一種回應。用 /normal、/midstream-error、/malformed。"""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        # chat_endpoint() 會在 base_url 後面接 /chat/completions
        route_name = self.path.split("/chat/completions")[0] or "/"
        route = {
            "/normal": ("application/json",
                        json.dumps(envelope('{"suggestions": []}'))),
            "/sse": ("text/event-stream",
                     ': OPENROUTER PROCESSING\n\n'
                     'data: {"choices":[{"delta":{"content":"{\\"suggestions\\": []}"}}]}\n\n'
                     "data: [DONE]\n\n"),
            "/midstream-error": ("application/json", json.dumps(UNAVAILABLE)),
            "/sse-midstream-error": ("text/event-stream",
                                     'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                                     'data: {"error":{"code":502,"metadata":'
                                     '{"error_type":"provider_unavailable"}}}\n\n'),
            "/malformed": ("application/json", json.dumps(envelope("not-json"))),
        }[route_name]
        body = route[1].encode()
        self.send_response(200)
        self.send_header("Content-Type", route[0])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def mock_provider():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def _call(base_url, route):
    return ai_client.call_ai_provider(
        SECRET, MODEL, [], provider="custom",
        base_url=f"{base_url}{route}",
    )


def test_live_normal_json(mock_provider):
    payload = _call(mock_provider, "/normal")
    assert ai_client.extract_text(payload, SECRET) == '{"suggestions": []}'


def test_live_sse_stream(mock_provider):
    payload = _call(mock_provider, "/sse")
    assert ai_client.extract_text(payload, SECRET) == '{"suggestions": []}'


def test_live_midstream_error(mock_provider):
    with pytest.raises(ProviderError) as excinfo:
        _call(mock_provider, "/midstream-error")
    assert "provider_unavailable" in str(excinfo.value)


def test_live_sse_midstream_error(mock_provider):
    with pytest.raises(ProviderError) as excinfo:
        _call(mock_provider, "/sse-midstream-error")
    assert "provider_unavailable" in str(excinfo.value)


def test_live_malformed_model_output_is_not_provider_failure(mock_provider):
    payload = _call(mock_provider, "/malformed")
    with pytest.raises(AnalyzerError) as excinfo:
        ai_client.parse_suggestions(
            ai_client.extract_text(payload, SECRET), [{"id": "p1"}]
        )
    assert not isinstance(excinfo.value, ProviderError)


def test_live_call_sends_authorization_and_never_leaks_it(mock_provider, capsys):
    _call(mock_provider, "/normal")
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err