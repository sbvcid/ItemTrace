"""AI provider client：OpenAI Chat Completions 相容的請求與回應驗證。

server 端的 `/api/items/{id}/ai/analyze` 與外部工具 `tools/analyze_item.py`
共用這一份 —— 請求怎麼組、照片怎麼編碼、模型輸出怎麼驗證，只有一份規則，
兩邊不會漂移。

刻意只用標準函式庫（urllib），不引入 OpenAI SDK 或其他 dependency：
專案從頭到尾不要求 pip install 額外套件（SPEC-v1 §9）。任何
OpenAI Chat Completions 相容端點（OpenRouter、Google Gemini、Custom）
都用同一條程式碼路徑，差別只在 base_url 與是否送 response_format。
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import urllib.error
import urllib.request

from .ai_config import (
    DEFAULT_BASE_URL,
    PROVIDER,
    AiConfigError,
    chat_endpoint,
    redact,
)
from .models import attribute_key

#: 這一輪只認這些欄位。不確定就不輸出 —— 空陣列比猜測好。
ALLOWED_FIELDS = (
    "name",
    "brand",
    "model",
    "category",
    "condition",
    "identifier:serial",
    "identifier:imei",
    "identifier:barcode",
)

#: 固定欄位之外，模型可以用 attribute:<key> 表達「值得記住但放不進固定欄位」
#: 的資訊（收據的店家/金額/日期、物品顏色、場合……）。key 的形狀由
#: shop/models.py 的 ATTRIBUTE_KEY_PATTERN 強制。
ATTRIBUTE_FIELD_EXAMPLE = "attribute:<key>"

#: 一輪分析最多接受幾筆建議。防止模型回傳無上限的陣列塞爆 pending。
MAX_SUGGESTIONS = 24

PROMPT = """\
你是 ItemTrace 的整理助手。請看這些照片，幫使用者把這筆紀錄整理成乾淨的資料。

固定欄位（照片支持哪個就輸出哪個）：
- name：品名（自然、完整的稱呼）
- brand：品牌
- model：型號
- category：分類（例如 主機板 / 顯示卡 / 工具 / 家電 / 文件 / 收據）
- condition：外觀與品況
- identifier:serial：序號 / 產品序號 / SN
- identifier:imei：IMEI
- identifier:barcode：條碼

固定欄位放不下、但值得記住的資訊，用 attribute:<key> 表達：
- key 用小寫英數與底線（snake_case），例如 attribute:vendor（店家）、
  attribute:amount（金額）、attribute:purchase_date（購買日期）、
  attribute:color（顏色）。
- value 是一段簡短文字。
- 一般性的整體描述（這東西是什麼、有什麼特別）用 attribute:description。

規則：
1. 只輸出你真的從照片上讀到的東西。不確定就不要輸出該欄位。
2. 序號、IMEI、條碼必須逐字照抄照片上的字元，不要腦補常見格式。
3. 如果同一個欄位在不同照片上讀到不同的值，以你最有把握的那個為準，
   並給它最高的 confidence。
4. source_photo_index 是你讀到該值的照片索引（從 0 開始）。
   序號請務必指向那張拍到標籤／序號的照片。
5. 照片順序就是給定的順序，不要重新編號。
6. 若提供了「目前已知資訊」，那可能是舊的、不完整的、甚至錯誤的：
   以照片為準提出更新；仍然正確的欄位可以照原值重新提出。
   使用者自己的備註不需要重複建議。
7. 完全讀不到就回傳空的 suggestions 陣列。不要解釋，不要客套。
"""

#: 照片縮圖邊長。手機原圖 3~5MB，base64 會再膨脹 33%，直接送整批容易爆。
MAX_SIDE = 1024
JPEG_QUALITY = 82

#: 一輪分析最多送幾張照片。
MAX_PHOTOS = 8

#: 呼叫 provider 的逾時（秒）。
TIMEOUT = 120

AnalyzerError = AiConfigError


class ProviderError(AnalyzerError):
    """Provider 本身的失敗（transport / HTTP / 串流中途的 error 事件）。

    為什麼要和「模型輸出格式錯誤」分開：provider 掛掉或暫時不可用時，
    舊的訊息會說「AI 服務回應格式不如預期」—— 把上游故障講成模型的
    問題。使用者看到會以為要改 prompt 或換模型，而實際上只要等一下再試。

    繼承 AnalyzerError，所以所有既有的 `except AnalyzerError` 都不用改；
    要區分的呼叫端可以 specifically 抓這個型別。
    """


#: provider error 物件裡只挑這些欄位進對外訊息。不整包 dump provider
#: 回應 —— 回應可能夾帶不該外流的內容，而且會被誤讀成「格式錯誤」。
_ERROR_SAFE_FIELDS = ("code", "type", "message")
_ERROR_METADATA_SAFE_FIELDS = ("error_type", "provider")

#: 判斷「看起來像 SSE」的開頭。SSE 註解行（`: ...`）也算。
_SSE_PREFIXES = ("data:", "data :", ":", "event:", "id:", "retry:")


def _describe_provider_error(error: object, model: str) -> str:
    """把 provider 的 error 物件壓成一句可安全顯示的話。

    只留白名單欄位；message 截斷。呼叫端負責再過 redact。
    """
    parts: list[str] = []

    if isinstance(error, str):
        # 有些端點的 error 就是字串（例如 {"error": "bad key ..."}）
        return (
            f"AI 服務暫時無法使用（model={model}）：{error.strip()[:200]}"
        )
    if not isinstance(error, dict):
        return f"AI 服務暫時無法使用（model={model}）：provider 回報了無法解析的錯誤"

    metadata = error.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    code = error.get("code")
    if isinstance(code, int) and not isinstance(code, bool):
        parts.append(f"HTTP {code}")
    for name in _ERROR_METADATA_SAFE_FIELDS:
        value = metadata.get(name)
        if isinstance(value, str) and value:
            parts.append(value)
    for name in _ERROR_SAFE_FIELDS:
        value = error.get(name)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip()[:200])
            break

    detail = "，".join(dict.fromkeys(parts)) or "provider 未提供原因"
    return f"AI 服務暫時無法使用（model={model}）：{detail}"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # attribute:<key> 的 key 是動態的，不能列舉；用 pattern 讓
                    # schema 與 parse_suggestions / repo 的驗證規則一致。
                    "field": {
                        "type": "string",
                        "pattern": (
                            "^(name|brand|model|category|condition|notes"
                            "|identifier:(serial|imei|barcode)"
                            "|attribute:[a-z][a-z0-9_]{0,39})$"
                        ),
                    },
                    "value": {"type": "string"},
                    "confidence": {"type": ["number", "null"]},
                    "source_photo_index": {"type": ["integer", "null"]},
                },
                "required": ["field", "value", "confidence", "source_photo_index"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


# ----------------------------------------------------------------------
# 照片：縮圖 → base64 data URL
# ----------------------------------------------------------------------


def encode_photo(data: bytes, filename: str) -> tuple[bytes, str]:
    """縮到 MAX_SIDE 並轉 JPEG。沒有 Pillow 就原封不動送出去。"""
    try:
        from PIL import Image
    except ImportError:
        return data, mimetypes.guess_type(filename)[0] or "image/jpeg"

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
            return buffer.getvalue(), "image/jpeg"
    except Exception:
        # 壞檔或不是圖片就照原樣送，讓模型自己判斷
        return data, mimetypes.guess_type(filename)[0] or "image/jpeg"


def photo_data_url(data: bytes, filename: str) -> str:
    """ItemTrace 的照片在區網內、不是公開網址，所以必須用 base64 data URL。

    絕對不能把區網網址交給第三方 —— 那等於把你的內網位置與照片暴露出去。
    """
    payload, mime = encode_photo(data, filename)
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


# ----------------------------------------------------------------------
# 送出與驗證
# ----------------------------------------------------------------------


def build_request_body(
    model: str,
    data_urls: list[str],
    *,
    provider: str = PROVIDER,
    context: str = "",
) -> dict:
    """OpenAI Chat Completions 相容的請求體。

    文字在最前面、照片在後面 —— OpenRouter 官方建議的順序，說是因為內容
   解析的實作如此。

    `context` 是這筆紀錄目前的已知資訊（Phase 2B 的「既有詮釋」）。
    它不是事實、可能過時或有誤，prompt 已明確要求以照片為準 ——
    有 context 時接在 PROMPT 之後以同一則 user 訊息送出。

    `response_format` 只在 OpenRouter 送：它的 json_schema strict 支援最完整。
    其他 OpenAI 相容端點（例如 Google Gemini）對 json_schema 的支援參差不齊
    （Gemini 相容層會靜默忽略不支援的參數），格式保護交給 parse_suggestions
    的嚴格驗證 —— 就算 endpoint 完全不理 response_format，格式不合也會報錯，
    不會有半套資料進來。

    刻意**不**加 OpenRouter 的 `provider` 欄位。實測：免費變體只對應到一個
    endpoint，加上 provider.require_parameters 會直接 404。
    """
    text = PROMPT
    if context.strip():
        text = (
            f"{PROMPT}\n\n"
            "## 這筆紀錄目前的已知資訊（可能過時或有誤，以照片為準）\n"
            f"{context.strip()}"
        )
    content: list[dict] = [{"type": "text", "text": text}]
    content.extend(
        {"type": "image_url", "image_url": {"url": url}} for url in data_urls
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    if provider == "openrouter":
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "item_suggestions",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            },
        }
    return body


def _sse_data_events(text: str):
    """把 SSE 文字切成每個事件�� data 值。

    - `: ...` 是註解（keep-alive、OpenRouter 的處理中提示）→ 忽略
    - `data:`  可以跨行，續行的 data 以換行接起來（SSE 規格）
    - 空行代表事件結束
    """
    data_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if stripped.startswith(":"):
            # 註解 / keep-alive，永遠不是 model output
            continue
        if stripped.startswith("data:"):
            data_lines.append(stripped[5:].lstrip())
            continue
        # event: / id: / retry: 之類欄位對我們沒有意义，忽略
    if data_lines:
        yield "\n".join(data_lines)


def _message_content(chunk: dict) -> str | None:
    """非串流 chunk 的完整內容（choices[0].message.content）。"""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return None


def _delta_content(chunk: dict) -> str:
    """串流 chunk 的增量內容（choices[0].delta.content）。"""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        return delta["content"]
    return ""


def _read_sse(text: str, model: str, api_key: str | None = None) -> dict:
    """解析 SSE 回應，回傳 chat completion 形狀的 dict。

    串流中途的 error 事件直接中斷並拋 ProviderError —— 絕不讓它掉到
    extract_text 去變成「格式不如預期」，也絕不產出半套建議。
    """
    complete: dict | None = None
    parts: list[str] = []
    saw_done = False

    for data in _sse_data_events(text):
        if data == "[DONE]":
            saw_done = True
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ProviderError(redact(
                f"AI 服務的串流事件不是合法 JSON（model={model}）："
                f"{data[:120]}（{exc.msg}）", api_key
            )) from None
        if not isinstance(chunk, dict):
            raise ProviderError(redact(
                f"AI 服務的串流事件不是 JSON 物件（model={model}）", api_key
            ))
        if chunk.get("error"):
            raise ProviderError(redact(
                _describe_provider_error(chunk["error"], model), api_key
            ))

        content = _message_content(chunk)
        if content is not None:
            complete = chunk
            parts = [content]
        else:
            delta = _delta_content(chunk)
            if delta:
                parts.append(delta)

    if complete is not None:
        return complete
    if parts:
        # 增量片段自己合成一個完整回應，沿用既有 extract_text 的路徑
        return {"choices": [{"message": {"content": "".join(parts)}}]}
    if saw_done:
        return {"choices": [{"message": {"content": ""}}]}
    raise ProviderError(redact(
        f"AI 服務的串流沒有任何內容就結束了（model={model}）", api_key
    ))


def decode_provider_response(
    raw: bytes, *, content_type: str = "", api_key: str | None = None,
    model: str = "",
) -> dict:
    """把 provider 回應的原始 bytes 解析成 chat completion dict。

    同時接受兩種形狀：
      * 一般 JSON（我們的請求沒有 stream=true，這是正常情況）
      * SSE 串流（中間層／部分 provider 會用這個形狀送回來）

    provider 自己回報的 error（不論在 JSON 還是 SSE 事件裡）一律轉成
    ProviderError，不會流到 extract_text 去被誤標成格式錯誤。
    """
    text = raw.decode("utf-8", "replace")
    is_sse = "text/event-stream" in content_type.lower() or text.lstrip().startswith(
        _SSE_PREFIXES
    )

    if is_sse:
        return _read_sse(text, model, api_key)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(redact(
            f"AI 服務回應不是合法 JSON（model={model}）："
            f"{text.strip()[:120]}（{exc.msg}）", api_key
        )) from None
    if not isinstance(payload, dict):
        raise ProviderError(redact(
            f"AI 服務回應不是 JSON 物件（model={model}）", api_key
        ))
    if payload.get("error"):
        # 在拋出前就遮蔽：例外本身不該帶著 key 四處走。
        raise ProviderError(redact(
            _describe_provider_error(payload["error"], model), api_key
        ))
    return payload


def call_ai_provider(
    api_key: str,
    model: str,
    data_urls: list[str],
    *,
    provider: str = PROVIDER,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = TIMEOUT,
    context: str = "",
) -> dict:
    """對任意 OpenAI 相容端點送出 chat completions 請求，回傳原始 JSON。

    `context` 是這筆紀錄目前的已知資訊（可為空）。舊呼叫端（外部 adapter）
    不傳也完全相容。

    沒有重試：失敗就是失敗（tests/test_analyze_item.py 明確斷言只嘗試
    一次、且不換模型）。provider 暫時不可用時使用者再按一次即可。
    """
    body = json.dumps(
        build_request_body(model, data_urls, provider=provider, context=context)
    ).encode("utf-8")
    endpoint = chat_endpoint(provider, base_url)
    request = urllib.request.Request(endpoint, data=body, method="POST")
    request.add_header("Authorization", "Bearer " + api_key)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        # HTTP 層級的失敗一律是 provider failure，不是模型輸出問題。
        # 訊息格式維持原樣，既有呼叫端與測試都靠它。
        detail = redact(exc.read().decode("utf-8", "replace")[:300], api_key)
        raise ProviderError(
            f"AI 服務回應 {exc.code}（model={model}）：{detail}"
        ) from None
    except urllib.error.URLError as exc:
        raise ProviderError(
            f"連不到 AI 服務（model={model}）：{exc.reason}"
        ) from None
    return decode_provider_response(
        raw, content_type=content_type, api_key=api_key, model=model
    )


def extract_text(response: dict, api_key: str | None = None) -> str:
    # 防禦性：provider 自己回報的 error 不該走到「格式不如預期」這裡。
    # call_ai_provider 已經擋過，但 extract_text 是公開函式，
    # 這個判斷必須對任何呼叫端都成立。
    if isinstance(response, dict) and response.get("error"):
        raise ProviderError(redact(
            _describe_provider_error(response["error"], ""), api_key
        ))
    try:
        return response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        # 這裡是「provider 正常回應，但回應框不是 chat completion」——
        # 跟「provider 故障」不同，所以不是 ProviderError。
        raise AnalyzerError(
            "AI 服務回應格式不如預期："
            + redact(json.dumps(response, ensure_ascii=False)[:300], api_key)
        ) from None


#: Markdown code fence 的開／閉標記。
CODE_FENCE = "```"


def strip_code_fence(text: str) -> str:
    """移除**完整的外層** Markdown code fence，否則原樣回傳。

    只做這一種最小處理，而且刻意非常嚴格 —— 因為寬鬆的「修復」會讓格式
    不合格的模型輸出被當成合格，之後的驗證就形同虛設。所以：

    * 必須整段文字就是一個 fence（去掉前後空白後），前後有自然語言一律
      不處理 —— 那不是 fence，是模型在講話。
    * 開頭的 ``` 後可以跟語言標記（`json`、`JSON`…），也可以沒有。
    * 必須有閉合的 ```；只有開頭沒有結尾（輸出被截斷）是**不完整**的
      fence，那種情況要報錯，不能猜內容到哪裡結束。

    回傳去掉 fence 之後的字串，交給 `json.loads` 做正式解析 —— 這個函式
    不判斷內容是不是 JSON。
    """
    stripped = text.strip()
    if not stripped.startswith(CODE_FENCE):
        return text

    # 去掉開頭的 ``` 與同一行上的語言標記。
    first_newline = stripped.find("\n")
    if first_newline == -1:
        # 只有 ```` 開頭一行、沒有換行 → 不是完整 fence。
        return text
    opening_line = stripped[:first_newline].strip()
    if not opening_line.startswith(CODE_FENCE):
        return text
    # 語言標記只允許一般識別字元（字母、數字、+ - # _）。
    # `\`\`\`json {"x": 1}` 這種「開頭後直接接內容」的不是 fence 的開頭，
    # 是模型亂寫 —— 維持原樣讓 json.loads 失敗。
    language = opening_line[len(CODE_FENCE):].strip()
    if language and not all(
        ch.isalnum() or ch in "+-#_" for ch in language
    ):
        return text

    body = stripped[first_newline + 1:]

    # 結尾必須是**單獨一行**的 ```（該行去掉前後空白後就是 ```）。
    # 要求獨立成行是刻意的：Markdown 規定閉合 fence 自己佔一行，而
    # `{"suggestions": []}``` 這種黏在一起的不是 fence，猜測它是不是 fence
    # 就會變成寬鬆修復。
    lines = body.rstrip().split("\n")
    if not lines or lines[-1].strip() != CODE_FENCE:
        return text

    return "\n".join(lines[:-1]).strip()


def parse_suggestions(text: str, photos: list[dict]) -> list[dict]:
    """嚴格驗證模型輸出。

    模型有時會把 JSON 包在 Markdown code fence 裡（`` ```json {...} ``` ``），
    所以解析前先用 `strip_code_fence` 移除那個包裝層。**只有**完整明確的
    外層 fence 會被移除：前後夾帶自然語言、或 fence 沒閉合，都照原樣送進
    `json.loads` 並失敗 —— 不做「從任意輸出裡找第一個 { 」那種寬鬆修復，
    那會讓不合格的輸出被當成合格。

    fence 移除之後，所有資料驗證完全不變。
    """
    try:
        payload = json.loads(strip_code_fence(text))
    except json.JSONDecodeError as exc:
        preview = text.strip()[:200]
        raise AnalyzerError(f"模型輸出不是合法 JSON：{preview}（{exc}）") from None

    if not isinstance(payload, dict) or "suggestions" not in payload:
        raise AnalyzerError("模型輸出缺少 suggestions 欄位")
    raw = payload["suggestions"]
    if not isinstance(raw, list):
        raise AnalyzerError("suggestions 必須是陣列")
    if len(raw) > MAX_SUGGESTIONS:
        raise AnalyzerError(
            f"建議數量超過上限（{len(raw)} > {MAX_SUGGESTIONS}）"
        )

    validated: list[dict] = []
    for position, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise AnalyzerError(f"第 {position + 1} 筆建議不是物件")

        field = entry.get("field")
        if not isinstance(field, str) or (
            field not in ALLOWED_FIELDS and attribute_key(field) is None
        ):
            raise AnalyzerError(
                f"第 {position + 1} 筆建議的欄位不在白名單：{field!r}"
                f"（可用 {ATTRIBUTE_FIELD_EXAMPLE} 表達自訂屬性）"
            )

        value = entry.get("value")
        if not isinstance(value, str) or not value.strip():
            raise AnalyzerError(f"第 {position + 1} 筆建議的 value 不是非空字串")

        confidence = entry.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise AnalyzerError(
                    f"第 {position + 1} 筆建議的 confidence 不是數字或 null"
                )
            if not 0.0 <= float(confidence) <= 1.0:
                raise AnalyzerError(
                    f"第 {position + 1} 筆建議的 confidence 超出 0~1：{confidence}"
                )

        index = entry.get("source_photo_index")
        photo_id = None
        if index is not None:
            if isinstance(index, bool) or not isinstance(index, int):
                raise AnalyzerError(
                    f"第 {position + 1} 筆建議的 source_photo_index 不是整數或 null"
                )
            if not 0 <= index < len(photos):
                raise AnalyzerError(
                    f"第 {position + 1} 筆建議的 source_photo_index={index} "
                    f"超出範圍（共 {len(photos)} 張照片）"
                )
            photo_id = photos[index]["id"]

        validated.append(
            {
                "field": field,
                "value": value.strip(),
                "confidence": None if confidence is None else float(confidence),
                "source_photo_id": photo_id,
            }
        )
    return validated
