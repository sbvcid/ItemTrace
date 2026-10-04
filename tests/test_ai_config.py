"""shop/ai_config.py —— AI 設定檔的唯一格式定義。

這個模組是「tools/ai_config.local.json 長什麼樣、怎麼驗、怎麼寫」的唯一
來源，`tools/analyze_item.py` 與 `/settings` 頁面都 import 它。

兩條不變量在這裡被釘死：
  1. `AiSettings`（給人看的那個）沒有 api_key 欄位
  2. 回傳給瀏覽器的東西永遠不含 key
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT))

from shop import ai_config  # noqa: E402

LOCAL_KEY = "sk-or-v1-TEST-LOCAL-KEY-0000000000"


def write(path: Path, **payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# 路徑：由程式決定，瀏覽器不能指定
# ----------------------------------------------------------------------


def test_config_path_is_inside_tools():
    assert ai_config.config_path().name == "ai_config.local.json"
    assert ai_config.config_path().parent.name == "tools"
    assert ai_config.config_path().parent.parent == ROOT


def test_example_path_exists():
    assert ai_config.example_path().name == "ai_config.example.json"
    assert ai_config.example_path().exists(), "example 設定檔必須存在"


def test_example_config_is_not_a_real_key():
    payload = json.loads(ai_config.example_path().read_text(encoding="utf-8"))
    assert payload["api_key"] == "PASTE_OPENROUTER_API_KEY_HERE"
    assert "sk-or-v1-" not in payload["api_key"]


# ----------------------------------------------------------------------
# read_settings：給人看的狀態，永遠不含 key
# ----------------------------------------------------------------------


def test_missing_file_is_not_an_error(tmp_path):
    settings = ai_config.read_settings(tmp_path / "nope.json")
    assert settings.configured is False
    assert settings.exists is False
    assert settings.model == ai_config.DEFAULT_MODEL
    assert settings.provider == "openrouter"


def test_existing_file_reports_configured_without_the_key(tmp_path):
    settings = ai_config.read_settings(
        write(tmp_path / "c.json", api_key=LOCAL_KEY, model="a/b:free")
    )
    assert settings.configured is True
    assert settings.model == "a/b:free"


def test_settings_object_has_no_api_key_field():
    """少一個欄位就少一個洩漏的機會。"""
    assert "api_key" not in ai_config.AiSettings.__dataclass_fields__
    assert "api_key" not in repr(ai_config.AiSettings(
        provider="openrouter", model="m", configured=True, exists=True,
        path=Path("x"),
    ))


def test_settings_json_never_contains_the_key(tmp_path):
    settings = ai_config.read_settings(
        write(tmp_path / "c.json", api_key=LOCAL_KEY, model="m")
    )
    assert LOCAL_KEY not in json.dumps({
        "provider": settings.provider,
        "configured": settings.configured,
        "model": settings.model,
    })


def test_file_without_key_is_not_configured(tmp_path):
    settings = ai_config.read_settings(write(tmp_path / "c.json", model="m"))
    assert settings.configured is False
    assert settings.exists is True


def test_read_accepts_utf8_bom(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"api_key": LOCAL_KEY}), encoding="utf-8-sig")
    assert ai_config.read_settings(path).configured is True


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ('{"api_key": "x", oops', "不是合法 JSON"),
        ("[1, 2, 3]", "必須是 JSON 物件"),
        ('{"api_key": 123}', "api_key 必須是字串"),
        ('{"model": 123}', "model 必須是字串"),
    ],
)
def test_malformed_config_is_reported(tmp_path, payload, fragment):
    path = tmp_path / "c.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ai_config.AiConfigError) as excinfo:
        ai_config.read_settings(path)
    assert fragment in str(excinfo.value)


def test_malformed_config_error_never_leaks_the_key(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"api_key": "' + LOCAL_KEY + '", oops', encoding="utf-8")
    with pytest.raises(ai_config.AiConfigError) as excinfo:
        ai_config.read_settings(path)
    assert LOCAL_KEY not in str(excinfo.value)


# ----------------------------------------------------------------------
# load_config：真的要拿 key 去用
# ----------------------------------------------------------------------


def test_load_config_requires_the_file(tmp_path):
    with pytest.raises(ai_config.AiConfigError) as excinfo:
        ai_config.load_config(tmp_path / "nope.json")
    assert "ai_config.local.json" in str(excinfo.value)
    assert "ai_config.example.json" in str(excinfo.value)
    assert "/settings" in str(excinfo.value), "訊息要告訴使用者有網頁設定頁"


def test_load_config_requires_a_key(tmp_path):
    with pytest.raises(ai_config.AiConfigError) as excinfo:
        ai_config.load_config(write(tmp_path / "c.json", model="m"))
    assert "缺少 api_key" in str(excinfo.value)


def test_load_config_returns_key_and_model(tmp_path):
    config = ai_config.load_config(
        write(tmp_path / "c.json", api_key=LOCAL_KEY, model="a/b:free")
    )
    assert config.api_key == LOCAL_KEY
    assert config.model == "a/b:free"


# ----------------------------------------------------------------------
# save_settings：寫回
# ----------------------------------------------------------------------


def test_save_creates_the_file(tmp_path):
    target = tmp_path / "c.json"
    settings = ai_config.save_settings(LOCAL_KEY, "a/b:free", target)
    assert settings.configured is True
    assert settings.model == "a/b:free"
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "api_key": LOCAL_KEY, "model": "a/b:free",
    }


def test_blank_key_keeps_the_existing_one(tmp_path):
    """密碼欄留白 ≠ 清除。這是最容易把 key 弄丟的地方。"""
    target = write(tmp_path / "c.json", api_key=LOCAL_KEY, model="old:free")

    for blank in (None, "", "   "):
        ai_config.save_settings(blank, "new:free", target)
        assert json.loads(target.read_text(encoding="utf-8"))["api_key"] == LOCAL_KEY, blank


def test_new_key_replaces_the_old_one(tmp_path):
    target = write(tmp_path / "c.json", api_key=LOCAL_KEY, model="m")
    new_key = "sk-or-v1-NEW-KEY-000000000000"
    ai_config.save_settings(new_key, "m", target)
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["api_key"] == new_key
    assert LOCAL_KEY not in stored["api_key"]


def test_blank_model_falls_back_to_default(tmp_path):
    target = write(tmp_path / "c.json", api_key=LOCAL_KEY, model="old:free")
    settings = ai_config.save_settings(None, "  ", target)
    assert settings.model == ai_config.DEFAULT_MODEL
    assert json.loads(target.read_text(encoding="utf-8"))["api_key"] == LOCAL_KEY


def test_saving_model_alone_keeps_the_key(tmp_path):
    target = write(tmp_path / "c.json", api_key=LOCAL_KEY, model="old:free")
    ai_config.save_settings(None, "new:free", target)
    assert json.loads(target.read_text(encoding="utf-8"))["api_key"] == LOCAL_KEY


def test_cannot_save_a_keyless_config_from_scratch(tmp_path):
    """還沒設定過、又沒填 key → 不要憑空造一個沒有 key 的設定檔。"""
    with pytest.raises(ai_config.AiConfigError) as excinfo:
        ai_config.save_settings(None, "m:free", tmp_path / "new.json")
    assert "尚未設定 API key" in str(excinfo.value)
    assert not (tmp_path / "new.json").exists()


def test_save_creates_the_tools_directory(tmp_path):
    target = tmp_path / "nested" / "c.json"
    ai_config.save_settings(LOCAL_KEY, "m:free", target)
    assert target.exists()


def test_save_is_atomic_no_temp_file_left(tmp_path):
    target = tmp_path / "c.json"
    ai_config.save_settings(LOCAL_KEY, "m:free", target)
    assert [p.name for p in tmp_path.iterdir()] == ["c.json"]


# ----------------------------------------------------------------------
# clear_api_key：明確的清除動作
# ----------------------------------------------------------------------


def test_clear_removes_the_key_but_keeps_the_model(tmp_path):
    target = write(tmp_path / "c.json", api_key=LOCAL_KEY, model="keep:free")
    settings = ai_config.clear_api_key(target)
    assert settings.configured is False
    assert settings.model == "keep:free"
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert "api_key" not in stored
    assert stored["model"] == "keep:free"


def test_clear_then_load_config_fails_cleanly(tmp_path):
    target = write(tmp_path / "c.json", api_key=LOCAL_KEY, model="m:free")
    ai_config.clear_api_key(target)
    with pytest.raises(ai_config.AiConfigError) as excinfo:
        ai_config.load_config(target)
    assert "缺少 api_key" in str(excinfo.value)


# ----------------------------------------------------------------------
# redact
# ----------------------------------------------------------------------


def test_redact_removes_a_known_secret():
    assert LOCAL_KEY not in ai_config.redact(f"壞了：{LOCAL_KEY}", LOCAL_KEY)


def test_redact_catches_keys_it_was_not_told_about():
    other = "sk-or-v1-somethingelse-entirely"
    assert other not in ai_config.redact(f"意外：{other}", None)


def test_redact_leaves_normal_text_alone():
    assert ai_config.redact("沒有 key 的訊息", None) == "沒有 key 的訊息"


# ----------------------------------------------------------------------
# repo 佈局：本機檔案不能被 Git 追蹤
# ----------------------------------------------------------------------


def test_local_config_is_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", "-v", "tools/ai_config.local.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, "tools/ai_config.local.json 沒有被 gitignore！"


def test_example_config_is_not_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", "tools/ai_config.example.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode != 0, "example 不該被 gitignore"


def test_local_config_is_not_tracked():
    result = subprocess.run(["git", "ls-files", "tools/"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    assert "ai_config.local.json" not in result.stdout


def test_every_non_example_json_in_tools_is_gitignored():
    """使用者的 ai_config.local.json 會存在，但它永遠不該被 commit。"""
    for path in sorted(TOOLS.glob("*.json")):
        if path.name == "ai_config.example.json":
            continue
        result = subprocess.run(
            ["git", "check-ignore", path.relative_to(ROOT).as_posix()],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, f"{path.name} 沒有被 gitignore！"


def test_readme_mentions_the_settings_page_and_the_file():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/settings" in readme
    assert "ai_config.local.json" in readme
    assert "sk-or-v1-" not in readme


def test_only_the_request_model_has_a_string_api_key_field():
    """api_key（字串）只能出現在「請求」模型裡，永遠不能是回應。

    回應模型帶 key 的話，GET /api/settings/ai 就會把 secret 送到瀏覽器。
    `api_key_changed: bool` 這種旗標是允許的 —— 它不是 key。
    """
    schemas = (ROOT / "shop" / "schemas.py").read_text(encoding="utf-8")
    blocks = re.findall(r"class (\w+)\(BaseModel\):(.*?)(?=\nclass |\Z)", schemas, re.S)
    with_key = {
        name for name, body in blocks
        if re.search(r"api_key\s*:\s*str", body)
    }
    assert with_key == {"AiSettingsUpdate"}, f"有其他模型帶字串型 api_key：{with_key}"


def test_response_models_have_no_key_shaped_field():
    """回應模型裡不能有 api_key / token / secret 之類的欄位。"""
    forbidden = ("api_key", "token", "secret", "password", "authorization")
    for name in ("AiSettingsOut", "AiSettingsSaved", "AiApiTestResult"):
        block = re.search(
            rf"class {name}\(BaseModel\):(.*?)(?=\nclass |\Z)",
            (ROOT / "shop" / "schemas.py").read_text(encoding="utf-8"), re.S,
        )
        assert block, name
        fields = re.findall(r"^\s{4}(\w+):", block.group(1), re.M)
        assert not [f for f in fields if f in forbidden], f"{name}: {fields}"


def test_the_request_model_is_never_used_as_a_response():
    """AiSettingsUpdate 只能當輸入，不能被任何端點當回應型別。"""
    for name in ("api.py", "settings.py"):
        source = (ROOT / "shop" / name).read_text(encoding="utf-8")
        for match in re.finditer(r"response_model=([\w.]+)", source):
            assert "Update" not in match.group(1), f"{name}: {match.group(1)}"
