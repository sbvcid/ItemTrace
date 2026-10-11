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
from typing import Any
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
你是 ItemTrace 的整理助手。使用者會拍各種照片：商品、文件、收據、標籤，
也可能是風景、街景、人物活動、食物或日常片刻。請看這些照片，把這一筆
紀錄整理成乾淨、好找、好回想的資料。

固定欄位（照片支持哪個就輸出哪個；不確定就省略，不要為了填滿而輸出）：
- name：這筆紀錄的標題，不限商品 —— 例如「清晨的陽光」「雨天騎樓下的
  街景」「SONY A7M4 相機」。任何照片都應該有合適的標題。
- brand：品牌（只在照片、包裝或標籤上真的看到時才輸出）
- model：型號（同上）
- category：廣義分類（例如 主機板 / 顯示卡 / 工具 / 家電 / 文件 / 收據 /
  風景 / 街景 / 人物 / 活動 / 食物 / 動物 / 其他）
- condition：物品的外觀與品況（只有物品照片適用）
- identifier:serial：序號 / 產品序號 / SN
- identifier:imei：IMEI
- identifier:barcode：條碼

固定欄位放不下、但值得記住的資訊，用 attribute:<key> 表達：
- key 用小寫英數與底線（snake_case），例如 attribute:vendor（店家）、
  attribute:amount（金額）、attribute:purchase_date（購買日期）、
  attribute:color（顏色）、attribute:time_of_day（清晨／正午／黃昏）、
  attribute:weather（天氣）、attribute:mood（氛圍）。
- value 是一段簡短文字。
- 整體描述用 attribute:description：1–2 句，先寫看得見的特徵（見規則 3）。

規則：
1. 只輸出照片支持的內容，寧缺勿猜。不確定就省略該欄位；不要輸出空字串、
   「未知」或「不確定」之類的佔位值。識別碼（serial / IMEI / barcode）
   必須逐字照抄；讀不清楚就不要輸出，不要腦補常見格式。
2. 非商品照片（風景、街景、人物、活動、食物、日常片刻）：不要輸出品牌、
   型號、品況或識別碼 —— 改用看得見的標題與描述，例如「清晨的陽光」
   「傍晚的街景，招牌亮起」。看得出東西但認不出身分時也一樣：用看得見的
   描述當 name（例如「紅色馬克杯」）。
3. 嚴格禁止憑空補入：地點名稱、人物身分或姓名、日期與時間、事件或店家
   名稱 —— 除非照片上直接可見（招牌、路牌、票券或收據上的文字）。
   氛圍、天氣、時段這類 attribute 也要有看得見的依據（陽光角度、雨痕、
   積水、燈光、陰影）才輸出。attribute:description 先寫確定看得見的
   （顏色、形狀、材質、明顯特徵），不確定的推測用「看起來像……」表示；
   連是什麼都看不出來也一樣，只描述看得到的。
4. 同一個欄位在不同照片讀到不同值時，不要自行合併或默默擇一：把不同的
   值分別輸出（同一個欄位可以有多筆建議），讓系統彙整並標示衝突；只有
   你能確定是同一實物的讀取變體（大小寫、明顯筆誤）時才擇一。兩張標籤
   寫不同品牌 —— 兩個值都要提出。
5. source_photo_index 是你讀到該值的照片索引（從 0 開始）。
   序號請務必指向那張拍到標籤／序號的照片。
6. 照片順序就是給定的順序，不要重新編號。
7. 若提供了「紀錄上下文」（包含目前狀態、識別碼、照片觀測、歷史修改與歷次 AI 判讀）：
   - 這是整筆紀錄的完整演進脈絡：請綜合「本次照片證據」、「目前狀態」與「歷史修改」重新理解整筆紀錄。
   - 使用者的歷史修正與手動輸入是關鍵事實與意圖依據：切勿盲目推翻使用者的修正。使用者已明確拒絕（rejected）或撤回（undone）的值，在沒有新證據時不要重複提出；若本次新照片提供實質、明確的新證據重新支持該值，可以再次提出，但那只會進入待確認清單 —— 系統不會自動套用被拒絕或撤回過的值（「禁止靜默自動套用」不等於「禁止再次提出」）。
   - 新證據評估：當新追加的照片有更清楚的銘牌、型號標籤、包裝或收據支持時，應勇於提出更精準的新判讀來修訂舊資料；但若新證據模糊、不完整或不足以推翻現有合理內容，應尊重並保留現有狀態，不要隨意以粗略猜測覆蓋。
   - 歷史存在矛盾時（如照片與舊備註不同、或多張照片標籤不一）：以可查證的照片證據為準，若多張照片各有依據則依規則 4 分別提出。
   - 仍然正確的欄位可以照原值重新提出；使用者自己的備註不需要重複建議。
8. 完全讀不到就回傳空的 suggestions 陣列。不要解釋，不要客套。
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
            "## 這筆紀錄的完整背景與上下文（包含目前狀態、歷史修改與拍攝觀測）\n"
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


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_analysis_context(
    item: Any,
    *,
    photos: list[Any] | None = None,
    all_photos: list[Any] | None = None,
    observations: list[Any] | None = None,
    identifiers: list[Any] | None = None,
    suggestions: list[Any] | None = None,
    events: list[Any] | None = None,
) -> str:
    """組裝供 Vision 模型重新理解整筆紀錄的結構化 Markdown 上下文。

    兩條管線（核心 API 與 tools/analyze_item.py）共用此函式，保證語意與結構一致。
    支援傳入 dict 或 dataclass 物件。
    """
    lines = ["## 【紀錄完整上下文（供重新理解與修訂）】"]

    # 1. 目前紀錄狀態
    lines.append("### 【目前紀錄狀態】")
    for k in ("name", "brand", "model", "category", "condition", "notes"):
        v = _obj_get(item, k)
        if v:
            lines.append(f"- {k}: {v}")
        else:
            lines.append(f"- {k}: （未填寫）")
    attrs = _obj_get(item, "attributes")
    if attrs:
        if isinstance(attrs, dict):
            lines.append(
                "- attributes: "
                + json.dumps(attrs, ensure_ascii=False, sort_keys=True)
            )
        else:
            lines.append(f"- attributes: {attrs}")

    # 2. 已登記識別碼
    ident_list = identifiers or []
    lines.append(f"\n### 【已登記識別碼（共 {len(ident_list)} 筆）】")
    if ident_list:
        for ident in ident_list:
            k = _obj_get(ident, "kind")
            val = _obj_get(ident, "value")
            src_photo = _obj_get(ident, "source_photo_id")
            extra = f"（來源照片: {src_photo}）" if src_photo else ""
            lines.append(f"- {k}: {val} {extra}".rstrip())
    else:
        lines.append("- （目前無已登記識別碼）")

    # 3. 本次分析照片與觀測
    all_p = all_photos if all_photos is not None else (photos or [])
    target_p = photos if photos is not None else all_p
    lines.append(f"\n### 【本次分析照片與觀測（共 {len(target_p)} 張）】")
    if len(all_p) > len(target_p):
        lines.append(
            f"（注意：商品總共有 {len(all_p)} 張原始照片，本次選取了 {len(target_p)} 張關鍵照片，"
            "包含早期建檔、關聯識別碼與最新追加照片）"
        )

    obs_list = observations or []
    obs_map = {_obj_get(o, "id"): o for o in obs_list if _obj_get(o, "id")}
    ident_photo_ids = {
        _obj_get(ident, "source_photo_id")
        for ident in ident_list
        if _obj_get(ident, "source_photo_id")
    }

    for idx, photo in enumerate(target_p):
        obs_id = _obj_get(photo, "observation_id")
        obs = obs_map.get(obs_id) if obs_id else None
        obs_desc = f"，觀測: {_obj_get(obs, 'kind')}" if obs else ""
        obs_note = _obj_get(obs, "note") if obs else None
        if obs_note:
            obs_desc += f"（{obs_note}）"
        time_desc = (
            _obj_get(photo, "captured_at")
            or _obj_get(photo, "created_at")
            or "未知時間"
        )
        photo_id = _obj_get(photo, "id")
        p_orig = _obj_get(photo, "orig_name") or _obj_get(photo, "filename") or ""

        tags = []
        if all_p and photo_id == _obj_get(all_p[0], "id"):
            tags.append("初始建檔照片")
        else:
            tags.append("後續追加照片")
        if photo_id in ident_photo_ids:
            tags.append("含識別碼證據")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(
            f"- [Photo {idx}] {p_orig}（時間: {time_desc}{obs_desc}）{tag_str}"
        )

    # 4. 重要歷史修改
    lines.append("\n### 【重要歷史修改】")
    hist_lines = []
    undone_ids = set()
    seen_edits = set()
    if events:
        for ev in events:
            ev_type = _obj_get(ev, "type")
            ev_actor = _obj_get(ev, "actor")
            ev_field = _obj_get(ev, "field")
            ev_created_at = _obj_get(ev, "created_at")
            ev_prev = _obj_get(ev, "prev_value")
            ev_next = _obj_get(ev, "next_value")
            ev_entity_id = _obj_get(ev, "entity_id")

            if ev_type == "suggestion.undone":
                if ev_entity_id:
                    undone_ids.add(ev_entity_id)
                hist_lines.append(
                    f"- {ev_created_at} 使用者先前撤回（Undo）了 {ev_field} 的自動套用（恢復為 {ev_next!r}）"
                )
            elif ev_type == "field.changed" and ev_actor == "user":
                key = (ev_field, str(ev_next))
                if key not in seen_edits:
                    seen_edits.add(key)
                    hist_lines.append(
                        f"- {ev_created_at} 使用者手動修改 {ev_field}: {ev_prev!r} -> {ev_next!r}"
                    )
            elif ev_type == "suggestion.auto_applied":
                hist_lines.append(
                    f"- {ev_created_at} 系統依據先前照片自動套用 {ev_field} = {ev_next!r}"
                )
            if len(hist_lines) >= 12:
                break

    if hist_lines:
        lines.extend(hist_lines)
    else:
        lines.append("- （無手動修改記錄或未取得歷史）")

    # 5. 歷次 AI 判讀與結果
    sugg_list = suggestions or []
    lines.append("\n### 【歷次 AI 判讀與結果】")
    sugg_lines = []

    # 不論呼叫端提供的順序為何（DB 預設是舊→新），一律按時間排序後取
    # **最近**的紀錄：配額要花在最新的拒絕／撤回／採納上，不能因為
    # 正序排序而優先保留最早、最可能已無關的紀錄。
    ordered = sorted(
        sugg_list,
        key=lambda s: (
            str(_obj_get(s, "created_at") or ""),
            str(_obj_get(s, "id") or ""),
        ),
    )
    rejected_suggs = [
        s for s in ordered if _obj_get(s, "status") == "rejected"
    ]
    accepted_suggs = [
        s for s in ordered if _obj_get(s, "status") == "accepted"
    ]
    superseded_suggs = [
        s for s in ordered if _obj_get(s, "status") == "superseded"
    ]

    for s in rejected_suggs[-8:]:
        s_id = _obj_get(s, "id")
        s_src = _obj_get(s, "source")
        s_field = _obj_get(s, "field")
        s_val = _obj_get(s, "value")
        if s_id in undone_ids or s_src == "auto":
            sugg_lines.append(
                f"- ↩️ 使用者先前撤回（Undo）：{s_field} = {s_val!r}"
                "（無新證據時請勿重複提議；此值永遠不會自動套用）"
            )
        else:
            sugg_lines.append(
                f"- ⚠️ 使用者明確拒絕：{s_field} = {s_val!r}"
                "（無新證據時請勿重複提議；此值永遠不會自動套用）"
            )

    for s in accepted_suggs[-8:]:
        s_src = _obj_get(s, "source")
        s_field = _obj_get(s, "field")
        s_val = _obj_get(s, "value")
        if s_src == "auto":
            sugg_lines.append(f"- ⚙️ 系統先前自動套用：{s_field} = {s_val!r}")
        else:
            sugg_lines.append(f"- ✓ 使用者已採納：{s_field} = {s_val!r}")

    for s in superseded_suggs[-4:]:
        s_field = _obj_get(s, "field")
        s_val = _obj_get(s, "value")
        sugg_lines.append(
            f"- ⚪ 先前曾提議但已由後續分析取代：{s_field} = {s_val!r}"
        )

    if sugg_lines:
        lines.extend(sugg_lines)
    else:
        lines.append("- （無先前 AI 判讀記錄）")

    # 6. 重新理解指引
    lines.append("\n### 【重新理解指引】")
    lines.append("- 結合新追加照片證據、既有照片與修改歷史，重新理解整筆紀錄。")
    lines.append(
        "- 使用者的手動修改與歷史修正代表已知事實；若新照片提供更明確、更清晰的實物證據（如銘牌、型號標籤、收據），請提出修正後的建議。"
    )
    lines.append(
        "- 若新照片證據不足或模糊，請維持現狀，切勿以粗略猜測隨意覆蓋。"
    )
    lines.append(
        "- 曾遭使用者明確拒絕或撤回（Undo）的值：沒有新的實質照片證據時，"
        "不要重複提出；若新照片提供了實質新證據重新支持該值，可以再次提出，"
        "但那只會是待確認建議 —— 系統絕不會自動套用被拒絕或撤回過的值。"
    )
    lines.append(
        "- 識別碼（serial / imei / barcode）必須精確照抄照片可見字元，並指向對應照片索引。"
    )

    return "\n".join(lines)


def select_photos_for_analysis(
    photos: list[Any],
    *,
    identifiers: list[Any] | None = None,
    observations: list[Any] | None = None,
    max_photos: int = MAX_PHOTOS,
) -> list[Any]:
    """全域照片精選政策（上限 max_photos，預設 8 張）。

    回傳張數保證不超過 max_photos（len(photos) <= max_photos 時全送）。
    >max_photos 時精選：
    1. 必須保留：Photo 0（初始建檔外觀基線）。
    2. 必須保留：最新追加照片（預算允許時保留最新 2 張，確保能獲取新證據；
       預算只有 2 張時保留最新 1 張）。
    3. 優先保留：包含已登記識別碼（serial/imei/barcode）證據的照片。
       - 名額＝預算扣除 Photo 0、最新保留與第二張基線後的餘額
         （8 張預算時為 5 張）。
       - 若識別碼照片 <= 名額：全數保留。
       - 若識別碼照片 > 名額：優先保留最新的名額張數（貼近最新狀態）；
         8 張預算時讓出 Photo 1 以容納更多識別碼證據。
       - 小預算（2~3 張）時基線與最新證據用盡預算，識別碼無名額。
    4. 餘額補齊：若識別碼照片少於名額，由最新照片往前依序補滿。若無識別碼照片，
       維持「最早 2 張＋最新 N-2 張」（N=2 時為最早 1 張＋最新 1 張）。
    5. 保持時間遞增順序，確保 source_photo_index 映射至切片精準無誤。
    """
    if max_photos <= 0:
        return []
    if max_photos == 1:
        return photos[:1]
    if len(photos) <= max_photos:
        return photos

    ident_list = identifiers or []
    referenced_ids = {
        _obj_get(ident, "source_photo_id")
        for ident in ident_list
        if _obj_get(ident, "source_photo_id")
    }

    ident_indices = [
        i for i, p in enumerate(photos) if _obj_get(p, "id") in referenced_ids
    ]

    if not ident_indices:
        if max_photos == 2:
            return [photos[0], photos[-1]]
        return photos[:2] + photos[-(max_photos - 2):]

    # 初始保留隨預算縮放：Photo 0 固定；最新照片（1~2 張）與第二張
    # 建檔基線只在預算允許時加入 —— 小預算不得先塞超過上限。
    selected: set[int] = {0}
    recent_slots = max_photos - 1
    if recent_slots >= 1:
        selected.add(len(photos) - 1)
    if recent_slots >= 2:
        selected.add(len(photos) - 2)
    if recent_slots >= 3:
        selected.add(1)

    ident_candidates = [i for i in ident_indices if i not in selected]
    avail = max_photos - len(selected)
    if len(ident_candidates) > avail and 1 in selected:
        # 識別碼候選超過名額時，讓出 Photo 1 給更多識別碼證據
        selected.remove(1)
        avail += 1

    if len(ident_candidates) <= avail:
        selected.update(ident_candidates)
    elif avail > 0:
        selected.update(ident_candidates[-avail:])

    for i in range(len(photos) - 1, -1, -1):
        if len(selected) >= max_photos:
            break
        selected.add(i)

    return [photos[i] for i in sorted(selected)]

