"""外部 AI adapter：OpenAI 相容 Vision → ItemTrace suggestions。

這支程式**在 ItemTrace 之外**。它只做一件事：把商品照片交給 Vision 模型，
把結果以 pending suggestion 的形式送進 ItemTrace。它沒有、也不該有任何
修改正式資料的能力 —— ItemTrace 是證據與事實的 system of record，
AI 只是 suggestion producer（SPEC-v1 §1、§13）。

邊界是**結構性**的，不只是慣例：ItemTraceClient 只公開三個方法
（讀商品、讀照片、建立 suggestion）。accept / reject / PATCH 沒有對應的
呼叫途徑，想呼叫也沒地方調。

設定只來自 tools/ai_config.local.json。刻意**不**讀環境變數、
也不找 ~/.config 或 Windows credential —— 這支 adapter 的憑證來源只有
它自己那個檔案，免得和同機器上其他 agent 共用同一把 key。
該檔案已被 .gitignore 排除。

AI 請求怎麼送、模型輸出怎麼驗證，只有 shop/ai_client.py 一份；
設定檔格式只有 shop/ai_config.py 一份。這裡不自己刻，
兩邊規則漂移過好幾次了。

用法：
    複製 tools/ai_config.example.json → tools/ai_config.local.json，填入 api_key
    python tools/analyze_item.py ITM-0001
    python tools/analyze_item.py ITM-0001 --base-url http://192.168.1.10:8731
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 設定檔的格式、驗證、遮蔽只有 shop/ai_config.py 一份；
# AI 請求與回應驗證只有 shop/ai_client.py 一份。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shop.ai_client import (  # noqa: E402
    ALLOWED_FIELDS,
    MAX_PHOTOS,
    PROMPT,
    TIMEOUT,
    AnalyzerError,
    build_request_body,
    call_ai_provider,
    extract_text,
    parse_suggestions,
    photo_data_url,
    strip_code_fence,
)
from shop.ai_config import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    MISSING_CONFIG,
    PROVIDER,
    AiConfig,
    AiConfigError,
    config_path,
    example_path,
    load_config,
    read_settings,
    redact,
    save_settings,
)

ItemTraceError = AnalyzerError

# 這些是從 shop.ai_config / shop.ai_client 轉出來的名字。
# analyze_item 是外部工具，測試與其他呼叫端仍然用
# analyze_item.load_config / .redact 這些名字，轉出來就不必到處改
# 匯入來源。實際定義只有 shop/ 裡那兩份。
__all__ = [
    "AiConfig",
    "AiConfigError",
    "ALLOWED_FIELDS",
    "AnalyzerError",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "ItemTraceClient",
    "ItemTraceError",
    "MISSING_CONFIG",
    "MAX_PHOTOS",
    "PROMPT",
    "TIMEOUT",
    "analyze",
    "build_request_body",
    "call_ai_provider",
    "config_path",
    "example_path",
    "extract_text",
    "load_config",
    "main",
    "parse_suggestions",
    "photo_data_url",
    "read_settings",
    "redact",
    "save_settings",
    "strip_code_fence",
]

#: ItemTrace 服務位置（不是 AI 端點）。AI 端點由設定檔的
#: provider / base_url 決定。
ITEMTRACE_BASE_URL = "http://127.0.0.1:8731"


# ----------------------------------------------------------------------
# ItemTrace 這邊：結構性限制在「只有讀取與建立 suggestion」
# ----------------------------------------------------------------------


class ItemTraceClient:
    """只讀商品／照片，加上建立 suggestion。

    刻意不提供 accept / reject / PATCH —— 這個 adapter 沒有修改正式資料的
    權限。`_request` 也會把 method + path 對照 ALLOWED_ROUTES 擋下來，
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
# 主流程
# ----------------------------------------------------------------------


def analyze(item_client: ItemTraceClient, api_key: str, item_id: str, *,
            model: str = DEFAULT_MODEL, max_photos: int = MAX_PHOTOS,
            provider_name: str = PROVIDER,
            base_url: str = DEFAULT_BASE_URL,
            provider=None, echo=None) -> list[dict]:
    """讀商品 → 取照片 → Vision → 驗證 → 建立 pending suggestion。

    provider / echo 是測試用的注入點（HTTP 與輸出都可假）。
    provider_name / base_url 決定呼叫哪個 OpenAI 相容端點。
    """
    provider = provider or call_ai_provider
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

    echo(f"AI 服務：{provider_name} / {model}（{len(data_urls)} 張）")
    response = provider(api_key, model, data_urls,
                        provider=provider_name, base_url=base_url)
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
        description="用 AI Vision 辨識商品照片，結果寫成 ItemTrace 的 pending 建議",
    )
    parser.add_argument("item_id", help="例如 ITM-0001")
    parser.add_argument("--base-url", default=ITEMTRACE_BASE_URL,
                        help=f"ItemTrace 服務位置（預設 {ITEMTRACE_BASE_URL}）")
    parser.add_argument("--model", default=None,
                        help="覆蓋設定檔裡的 model（預設用 ai_config.local.json 的值）")
    parser.add_argument("--max-photos", type=int, default=MAX_PHOTOS,
                        help=f"最多送幾張照片（預設 {MAX_PHOTOS}）")
    parser.add_argument("--quiet", action="store_true", help="不輸出進度")
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except AnalyzerError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    model = args.model or config.model
    echo = (lambda message: None) if args.quiet else (lambda message: print(message))
    try:
        created = analyze(
            ItemTraceClient(args.base_url),
            config.api_key,
            args.item_id,
            model=model,
            provider_name=config.provider,
            base_url=config.base_url,
            max_photos=args.max_photos,
            echo=echo,
        )
    except AnalyzerError as exc:
        print(redact(str(exc), config.api_key), file=sys.stderr)
        return 1
    echo(f"\n{args.item_id}：{len(created)} 筆 pending 建議已送出。")
    echo("接著到 ItemTrace 商品頁逐筆看過再接受 —— AI 不會自己決定。")
    return 0


# analyze_item 原先自己 import 的模組，現在集中在檔案頭；
# 這裡不再重複 import。


if __name__ == "__main__":
    raise SystemExit(main())
