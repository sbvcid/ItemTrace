"""外部 AI adapter：OpenRouter Vision → ItemTrace suggestions。

這支程式**在 ItemTrace 之外**。它只做一件事：把商品照片交給 Vision 模型，
把結果以 pending suggestion 的形式送進 ItemTrace。它沒有、也不該有任何
修改正式資料的能力 —— ItemTrace 是證據與事實的 system of record，
AI 只是 suggestion producer（SPEC-v1 §1、§13）。

邊界是**結構性**的，不只是慣例：ItemTraceClient 只公開三個方法
（讀商品、讀照片、建立 suggestion）。accept / reject / PATCH 沒有對應的
呼叫途徑，想呼叫也沒地方調。

用法：
    python tools/analyze_item.py ITM-0001
    python tools/analyze_item.py ITM-0001 --base-url http://192.168.1.10:8731

API key 從環境變數 OPENROUTER_API_KEY 讀，不從命令列參數、不寫檔。
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

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

#: 免費、支援圖片輸入的模型（2026-10 由 GET https://openrouter.ai/api/v1/models
#: 與 /models/{slug}/endpoints 實際確認）。
#:
#: 選 google/gemma-4-31b-it:free 時實測到兩個問題，都不影響正確性但影響可用性：
#:   1. 免費變體只對應一個 endpoint，加上 provider.require_parameters 會直接 404
#:   2. 該 endpoint（Google AI Studio）經常 429 rate-limited
#: qwen/qwen3.8-27b:free 有 17 個獨立上游（Wafer / Reka / DekaLLM / …），
#: 比較不會撞上單一 provider 的限流，而且 Qwen 的 vision 這條線本來就擅長
#: 讀標籤與序號。
#:
#: 刻意不設自動 fallback：不能因為免費模型失敗就改用付費的。要換模型請用
#: --model 明確指定，而且必須自己確認那是免費的。
DEFAULT_MODEL = "qwen/qwen3.8-27b:free"

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_BASE_URL = "http://127.0.0.1:8731"
MAX_PHOTOS = 8
TIMEOUT = 120

#: 照片縮圖邊長。手機原圖 3~5MB，base64 會再膨脹 33%，直接送整批容易爆。
MAX_SIDE = 1024
JPEG_QUALITY = 82

PROMPT = """\
你是商品建檔的輔助。請看這些照片，辨識商品的以下欄位：

- name：品名
- brand：品牌
- model：型號
- category：分類（例如 主機板 / 顯示卡 / 記憶體 / 硬碟 / 電源 / 機殼）
- condition：外觀與品況
- identifier:serial：序號 / 產品序號 / SN
- identifier:imei：IMEI
- identifier:barcode：條碼

規則：
1. 只輸出你真的從照片上讀到的東西。不確定就不要輸出該欄位。
2. 序號、IMEI、條碼必須逐字照抄照片上的字元，不要腦補常見格式。
3. 如果同一個欄位在不同照片上讀到不同的值，以你最有把握的那個為準，
   並給它最高的 confidence。
4. source_photo_index 是你讀到該值的照片索引（從 0 開始）。
   序號請務必指向那張拍到標籤／序號的照片。
5. 照片順序就是給定的順序，不要重新編號。
6. 完全讀不到就回傳空的 suggestions 陣列。不要解釋，不要客套。
"""


class AnalyzerError(Exception):
    """使用者可以自己處理掉的問題（設定、網路、模型輸出不合規）。"""


# ----------------------------------------------------------------------
# ItemTrace 這邊：結構性限制在「只有讀取與建立 suggestion」
# ----------------------------------------------------------------------


class ItemTraceClient:
    """只讀商品／照片，加上建立 suggestion。

    刻意不提供 accept / reject / PATCH —— 這個 adapter 沒有修改正式資料的
    權限。`_request` 也會把 method + path 對照 ALLOWED_ROUTES擋下來，
    就算日後有人加錯方法也會在送出前就爆掉。
    """

    ALLOWED_ROUTES = (
        ("GET", r"^/api/items/[^/]+$"),
        ("GET", r"^/api/items/[^/]+/suggestions$"),
        ("GET", r"^/files/.+$"),
        ("POST", r"^/api/items/[^/]+/suggestions$"),
    )

    def __init__(self, base_url: str, timeout: int = TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_item(self, item_id: str) -> dict:
        return self._request("GET", f"/api/items/{urllib.parse.quote(item_id)}")

    def list_suggestions(self, item_id: str) -> list[dict]:
        return self._request(
            "GET", f"/api/items/{urllib.parse.quote(item_id)}/suggestions"
        )

    def get_photo_bytes(self, filename: str) -> bytes:
        return self._request("GET", "/files/" + filename.lstrip("/"), raw=True)

    def create_suggestion(self, item_id: str, payload: dict) -> dict:
        return self._request(
            "POST",
            f"/api/items/{urllib.parse.quote(item_id)}/suggestions",
            body=payload,
        )

    def _request(self, method: str, path: str, body=None, raw: bool = False):
        if not any(
            method == m and re.match(pattern, path)
            for m, pattern in self.ALLOWED_ROUTES
        ):
            raise AnalyzerError(
                f"adapter 不得呼叫 {method} {path}："
                "這個 adapter 只讀商品與照片、建立 suggestion"
            )

        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise AnalyzerError(
                f"ItemTrace 回應 {exc.code}（{method} {path}）：{detail}"
            ) from None
        except urllib.error.URLError as exc:
            raise AnalyzerError(
                f"連不到 ItemTrace（{self.base_url}）：{exc.reason}。"
                " 服務有開嗎？--base-url 對嗎？"
            ) from None
        return payload if raw else json.loads(payload)


# ----------------------------------------------------------------------
# 照片：縮圖 → base64 data URL
# ----------------------------------------------------------------------


def encode_photo(data: bytes, filename: str) -> tuple[bytes, str]:
    """縮到 MAX_SIDE 並轉 JPEG。沒有 Pillow 就原封不動送出去。"""
    try:
        import io

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

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(ALLOWED_FIELDS)},
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


def build_request_body(model: str, data_urls: list[str]) -> dict:
    """OpenRouter chat completions。

    文字在最前面、照片在後面 —— OpenRouter 官方建議的順序，說是因為內容
    解析的實作如此。

    刻意**不**加 `provider.require_parameters`。實測：免費變體只對應到一個
    endpoint，加上這個約束會直接 404（"No endpoints found that can handle the
    requested parameters"，而且不計費）。真正保護 pipeline 的是 parse_suggestions
    的嚴格驗證 —— 就算 endpoint 忽略 response_format，格式不合也會報錯，
    不會有半套資料進來。
    """
    content: list[dict] = [{"type": "text", "text": PROMPT}]
    content.extend(
        {"type": "image_url", "image_url": {"url": url}} for url in data_urls
    )
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "item_suggestions",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            },
        },
    }


def redact(text: str, secret: str | None) -> str:
    """任何要顯示給使用者的文字都先過這裡。"""
    if secret and secret in text:
        text = text.replace(secret, "***")
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)


def call_openrouter(api_key: str, model: str, data_urls: list[str],
                    timeout: int = TIMEOUT) -> dict:
    body = json.dumps(build_request_body(model, data_urls)).encode("utf-8")
    request = urllib.request.Request(OPENROUTER_ENDPOINT, data=body, method="POST")
    request.add_header("Authorization", "Bearer " + api_key)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = redact(exc.read().decode("utf-8", "replace")[:300], api_key)
        raise AnalyzerError(
            f"OpenRouter 回應 {exc.code}（model={model}）：{detail}"
        ) from None
    except urllib.error.URLError as exc:
        raise AnalyzerError(f"連不到 OpenRouter：{exc.reason}") from None


def extract_text(response: dict, api_key: str | None = None) -> str:
    try:
        return response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise AnalyzerError(
            "OpenRouter 回應格式不如預期："
            + redact(json.dumps(response, ensure_ascii=False)[:300], api_key)
        ) from None


def parse_suggestions(text: str, photos: list[dict]) -> list[dict]:
    """嚴格驗證模型輸出。格式不合就直接報錯，不用 regex 猜測修復。"""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text.strip()[:200]
        raise AnalyzerError(f"模型輸出不是合法 JSON：{preview}（{exc}）") from None

    if not isinstance(payload, dict) or "suggestions" not in payload:
        raise AnalyzerError("模型輸出缺少 suggestions 欄位")
    raw = payload["suggestions"]
    if not isinstance(raw, list):
        raise AnalyzerError("suggestions 必須是陣列")

    validated: list[dict] = []
    for position, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise AnalyzerError(f"第 {position + 1} 筆建議不是物件")

        field = entry.get("field")
        if field not in ALLOWED_FIELDS:
            raise AnalyzerError(
                f"第 {position + 1} 筆建議的欄位不在白名單：{field!r}"
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


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------


def analyze(item_client: ItemTraceClient, api_key: str, item_id: str, *,
            model: str = DEFAULT_MODEL, max_photos: int = MAX_PHOTOS,
            provider=None, echo=None) -> list[dict]:
    """讀商品 → 取照片 → Vision → 驗證 → 建立 pending suggestion。

    provider / echo 是測試用的注入點（HTTP 與輸出都可假）。
    """
    provider = provider or call_openrouter
    echo = echo if echo is not None else (lambda message: None)

    detail = item_client.get_item(item_id)
    item = detail["item"]
    photos = [p for p in detail.get("photos", []) if p.get("role") == "original"]
    photos = photos[:max_photos]

    if not photos:
        raise AnalyzerError(
            f"{item_id} 沒有 original 照片，沒有東西可以辨識。"
            " 先用 Inbox 建檔並上傳照片。"
        )

    echo(f"ItemTrace：{item_id}「{item['name'] or '(未填品名)'}」，original 照片 {len(photos)} 張")

    data_urls = []
    for photo in photos:
        raw = item_client.get_photo_bytes(photo["filename"])
        data_urls.append(photo_data_url(raw, photo.get("orig_name") or photo["filename"]))
        echo(f"  已讀取 {photo['orig_name']}")

    echo(f"OpenRouter：{model}（{len(data_urls)} 張）")
    response = provider(api_key, model, data_urls)
    text = extract_text(response, api_key)
    suggestions = parse_suggestions(text, photos)

    if not suggestions:
        echo("模型沒有給出任何建議 —— 不確定就不輸出，這是預期的行為。")
        return []

    created = []
    for suggestion in suggestions:
        payload = {
            **suggestion,
            "source": "external",
            "model_name": model,
            "actor": "external",
        }
        row = item_client.create_suggestion(item_id, payload)
        created.append(row)
        photo_hint = payload["source_photo_id"] or "（無來源照片）"
        echo(f"  已建立 pending 建議 {payload['field']} = {payload['value']!r} "
             f"信心 {payload['confidence']} 來源照片 {photo_hint}")

    # 收尾再確認一次：pending 的數量確實增加了，而且沒有任何欄位被改動
    pending = [s for s in item_client.list_suggestions(item_id)
               if s["status"] == "pending"]
    if len(pending) < len(created):
        raise AnalyzerError(
            f"建立了 {len(created)} 筆建議，但 pending 只剩 {len(pending)} 筆 —— "
            "有東西被自動決定了，這是 bug"
        )
    after = item_client.get_item(item_id)["item"]
    for key in ("brand", "model", "name", "category", "condition", "notes"):
        if after[key] != item[key]:
            raise AnalyzerError(
                f"adapter 不該修改 items.{key}，但值變了 —— 這是 bug"
            )
    echo(f"完成：{len(created)} 筆 pending 建議，items 欄位未被修改。")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="analyze_item",
        description="用 OpenRouter Vision 辨識商品照片，結果寫成 ItemTrace 的 pending 建議",
    )
    parser.add_argument("item_id", help="例如 ITM-0001")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"ItemTrace 服務位置（預設 {DEFAULT_BASE_URL}）")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"OpenRouter 模型（預設 {DEFAULT_MODEL}，不會自動 fallback）")
    parser.add_argument("--max-photos", type=int, default=MAX_PHOTOS,
                        help=f"最多送幾張照片（預設 {MAX_PHOTOS}）")
    parser.add_argument("--quiet", action="store_true", help="不輸出進度")
    args = parser.parse_args(argv)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print(
            "找不到 OPENROUTER_API_KEY。\n"
            "  設定方式（不要把 key 寫進檔案或 commit）：\n"
            "    PowerShell  $env:OPENROUTER_API_KEY = '...'\n"
            "    cmd        set OPENROUTER_API_KEY=...",
            file=sys.stderr,
        )
        return 2

    echo = (lambda message: None) if args.quiet else (lambda message: print(message))
    try:
        created = analyze(
            ItemTraceClient(args.base_url),
            api_key,
            args.item_id,
            model=args.model,
            max_photos=args.max_photos,
            echo=echo,
        )
    except AnalyzerError as exc:
        print(redact(str(exc), api_key), file=sys.stderr)
        return 1
    echo(f"\n{args.item_id}：{len(created)} 筆 pending 建議已送出。")
    echo("接著到 ItemTrace 商品頁逐筆看過再接受 —— AI 不會自己決定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
