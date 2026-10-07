"""`/api/settings/ai` —— 在網頁上設定 AI 服務的 API key、provider 與 model。

安全性是這一頁的全部重點，所以先把規則寫在最前面：

1. **GET 永遠不回傳 key。** `shop/schemas.py` 的 AiSettingsOut 沒有
   api_key 欄位，回應組裝處也不碰 key —— 少一個欄位就少一個洩漏的機會。
   頁面只顯示「API Key：已設定」。

2. **key 只存在這台電腦的檔案裡。** 寫入類端點（存檔／清除／測試）
   會把 key 寫進 tools/ai_config.local.json（.gitignore、atomic write、
   0600），任何回應都不含 key。本專案沒有登入系統，而 server 刻意
   只服務受信任區網（config.json 的 server_host + 防火牆），區網裡
   任何裝置本來就能讀寫所有商品資料 —— 讓區網裝置（例如手機）
   也能操作 AI 設定，與那個信任模型一致。若不信任區網，請把
   server_host 改回 127.0.0.1，寫入類端點就只接受本機。

   判斷來源用的是 `request.client.host` —— 那是 socket 的對端位址，
   由 WebSocket/HTTP server 從連線本身取得。**不看 X-Forwarded-For**，
   實測過偽造該標頭不會改變 client.host（見 tests/test_settings_api.py）。

3. **API 不能指定路徑。** 設定檔位置由 `shop/ai_config.py` 決定，
   瀏覽器傳什麼 path／filename 都不進來。

4. **錯誤訊息不帶 key。** provider 的錯誤會經過 ai_config.redact()。
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request

from fastapi import APIRouter, Request

from . import ai_config
from . import print_config
from .ai_config import AiConfigError
from .errors import ValidationError
from .schemas import (
    AiApiTestResult,
    AiSettingsOut,
    AiSettingsSaved,
    AiSettingsUpdate,
    PrintSettingsOut,
    PrintSettingsUpdate,
)

router = APIRouter(tags=["settings"])

PROVIDER_TEST_TIMEOUT = 30


def is_loopback(request: Request) -> bool:
    """請求是否來自本機。

    只看 socket 對端位址。X-Forwarded-For / X-Real-IP 是使用者可控的標頭，
    拿來判斷權限就等於沒有判斷。
    """
    client = request.client
    if client is None or not client.host:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        # 測試用的 "testclient" 或非 IP 的主機名，一律視為不是本機。
        return False


def _settings_out(request: Request) -> AiSettingsOut:
    try:
        settings = ai_config.read_settings()
    except AiConfigError as exc:
        # 設定檔壞掉要讓使用者看得見、看得懂，但不能把檔案內容印出來
        raise ValidationError(ai_config.redact(str(exc))) from None
    return AiSettingsOut(
        provider=settings.provider,
        configured=settings.configured,
        model=settings.model,
        base_url=settings.base_url,
        default_model=ai_config.DEFAULT_MODEL,
        presets=dict(ai_config.PROVIDER_BASE_URLS),
        is_loopback=is_loopback(request),
        can_edit=True,
        config_file=f"tools/{ai_config.CONFIG_FILENAME}",
    )


@router.get("/api/settings/ai", response_model=AiSettingsOut)
def get_ai_settings(request: Request) -> AiSettingsOut:
    """讀取設定狀態。

    任何來源都可以讀 —— 回應裡沒有 key，只有「有沒有設定」、
    model 與 base_url。
    """
    return _settings_out(request)


@router.post("/api/settings/ai", response_model=AiSettingsSaved)
def update_ai_settings(
    body: AiSettingsUpdate, request: Request
) -> AiSettingsSaved:
    """儲存 provider / base_url / model 與／或 API key。

    `api_key` 留空 → 保留原本的 key。清除是另一個明確的動作。
    """
    try:
        before = ai_config.read_settings()
        saved = ai_config.save_settings(
            body.api_key, body.model, body.provider, body.base_url
        )
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None

    return AiSettingsSaved(
        provider=saved.provider,
        configured=saved.configured,
        model=saved.model,
        base_url=saved.base_url,
        api_key_changed=bool((body.api_key or "").strip()),
        model_changed=saved.model != before.model,
        provider_changed=saved.provider != before.provider,
        base_url_changed=saved.base_url != before.base_url,
    )


@router.post("/api/settings/ai/clear-key", response_model=AiSettingsSaved)
def clear_ai_key(request: Request) -> AiSettingsSaved:
    """清除 API key，保留 provider / base_url / model。

    密碼欄留白不算清除 —— 那樣按一次儲存就把 key 弄丟了。
    """
    try:
        saved = ai_config.clear_api_key()
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None
    return AiSettingsSaved(
        provider=saved.provider,
        configured=saved.configured,
        model=saved.model,
        base_url=saved.base_url,
        api_key_changed=True,
        model_changed=False,
    )


# ----------------------------------------------------------------------
# 列印設定
#
# 刻意**不做** loopback 限制。AI 設定會動到一把外部服務的 secret，
# 限制只有本機才寫是合理的；列印設定只是「預設印表機／預設範本」，
# 沒有機密，而且設定變更影響的只是這台電腦要送印到哪台機器 ——
# 能操作商品資料的區網裝置本來就能指定印表機（`/api/templates/{id}/print`
# 接受 printer 欄位）。在手機上改預設值是正常使用情境，不該被擋。
# ----------------------------------------------------------------------


def _print_settings_out() -> PrintSettingsOut:
    settings = print_config.read_settings()
    return PrintSettingsOut(
        printer=settings.printer,
        template_id=settings.template_id,
        exists=settings.exists,
        error=settings.error,
    )


@router.get("/api/settings/printing", response_model=PrintSettingsOut)
def get_print_settings() -> PrintSettingsOut:
    """讀取列印設定。

    任何來源都可以讀，跟商品資料同一個信任模型（同上）。
    印表機清單刻意不放進來：那是 Windows 的即時狀態，由
    `/api/printers` 單獨提供，設定檔只記「使用者選了哪一台」。
    """
    return _print_settings_out()


@router.post("/api/settings/printing", response_model=PrintSettingsOut)
def update_print_settings(body: PrintSettingsUpdate) -> PrintSettingsOut:
    """儲存預設印表機與預設範本。

    刻意不驗證印表機名稱或範本 ID 是否存在：Windows 的印表機可能改名或
    被移除，Template 也可能被刪除；硬擋只會讓使用者改了設定卻存不進去。
    真正使用時才會拿到明確錯誤（列印時 400 / 404）。
    """
    try:
        print_config.save_settings(body.printer, body.template_id)
    except OSError as exc:
        raise ValidationError(f"無法寫入列印設定：{exc}") from None
    return _print_settings_out()


@router.post("/api/settings/ai/test", response_model=AiApiTestResult)
def test_ai_api(body: AiSettingsUpdate, request: Request) -> AiApiTestResult:
    """用最小文字請求測試 provider。

    不讀 ItemTrace 商品、不送照片、不建立 suggestion、不修改任何東西 ——
    只確認「這把 key 加上這個 model 能不能通」。

    帶 `api_key` 進來時測的是「剛貼上、還沒存」的那把 key；留空則測已存的。
    `provider` / `base_url` 同理：帶進來就測剛填的，留空用已存的。
    """
    model = (body.model or "").strip()
    incoming = (body.api_key or "").strip()
    try:
        stored = ai_config.load_config()
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None

    api_key = incoming or stored.api_key
    model = model or stored.model
    incoming_provider = (body.provider or "").strip()
    provider = incoming_provider or stored.provider
    base_url = (body.base_url or "").strip()
    if not base_url:
        if incoming_provider:
            # 換了 provider 但沒給 base_url：用該 provider 的預設，
            # 不要沿用舊 provider 的 base_url（那是別的服務的位址）
            base_url = ai_config.PROVIDER_BASE_URLS.get(provider, "")
        if not base_url:
            base_url = stored.base_url
    try:
        endpoint = ai_config.chat_endpoint(provider, base_url)
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
    }).encode("utf-8")

    request_object = urllib.request.Request(
        endpoint, data=payload, method="POST"
    )
    request_object.add_header("Authorization", "Bearer " + api_key)
    request_object.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(
            request_object, timeout=PROVIDER_TEST_TIMEOUT
        ) as response:
            response.read()
        return AiApiTestResult(ok=True, model=model)
    except urllib.error.HTTPError as exc:
        detail = ai_config.redact(
            exc.read().decode("utf-8", "replace")[:300], api_key
        )
        raise ValidationError(f"API 測試失敗（{exc.code}）：{detail}") from None
    except urllib.error.URLError as exc:
        raise ValidationError(f"API 測試失敗：{exc.reason}") from None
