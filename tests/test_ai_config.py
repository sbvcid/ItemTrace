"""tools/ai_config.local.json 的設定載入與憑證隔離。

重點在兩件事：
  1. 設定**只**來自 tools/ai_config.local.json —— 不讀環境變數、不找別處
  2. 真實 API key 不會出現在任何輸出、錯誤或 exception
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SPEC = importlib.util.spec_from_file_location(
    "analyze_item_config", TOOLS / "analyze_item.py"
)
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules["analyze_item_config"] = analyzer
SPEC.loader.exec_module(analyzer)
# 別的測試檔會 import analyze_item；這裡先註冊，
# 免得這個檔案單獨跑時 ModuleNotFoundError。
sys.modules.setdefault("analyze_item", analyzer)

LOCAL_KEY = "sk-or-v1-CORRECT-LOCAL-KEY-0000000000"
GLOBAL_KEY = "sk-or-v1-WRONG-GLOBAL-KEY-000000000"


def write_config(path: Path, **overrides):
    payload = {"api_key": LOCAL_KEY, **overrides}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# 1. local config 可以正常讀取
# ----------------------------------------------------------------------


def test_local_config_is_read(tmp_path):
    config = analyzer.load_config(write_config(tmp_path / "ai_config.local.json"))
    assert config.api_key == LOCAL_KEY
    assert config.model == analyzer.DEFAULT_MODEL


def test_config_accepts_utf8_bom(tmp_path):
    """Windows 用記事本存 JSON 會加 BOM。"""
    path = tmp_path / "ai_config.local.json"
    path.write_text(json.dumps({"api_key": LOCAL_KEY}), encoding="utf-8-sig")
    assert analyzer.load_config(path).api_key == LOCAL_KEY


def test_config_path_is_inside_tools():
    assert analyzer.CONFIG_PATH.parent == analyzer.TOOLS_DIR
    assert analyzer.CONFIG_PATH.name == "ai_config.local.json"
    assert analyzer.EXAMPLE_PATH.name == "ai_config.example.json"
    assert analyzer.EXAMPLE_PATH.exists(), "example 設定檔必須存在"


# ----------------------------------------------------------------------
# 2. 缺 local config 時明確失敗
# ----------------------------------------------------------------------


def test_missing_config_is_a_clear_stop(tmp_path):
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.load_config(tmp_path / "ai_config.local.json")
    message = str(excinfo.value)
    assert "ai_config.local.json" in message
    assert "ai_config.example.json" in message


def test_missing_config_message_explains_how_to_create_it():
    message = analyzer.MISSING_CONFIG
    assert "複製 tools/ai_config.example.json" in message
    assert "→ tools/ai_config.local.json" in message
    assert "api_key" in message


def test_example_config_can_be_copied_and_used(tmp_path):
    """clone 的使用者複製 example、換掉 key 之後就能直接跑。"""
    copied = tmp_path / "ai_config.local.json"
    copied.write_text(
        analyzer.EXAMPLE_PATH.read_text(encoding="utf-8").replace(
            "PASTE_OPENROUTER_API_KEY_HERE", LOCAL_KEY
        ),
        encoding="utf-8",
    )
    config = analyzer.load_config(copied)
    assert config.api_key == LOCAL_KEY
    assert config.model == analyzer.DEFAULT_MODEL


def test_example_config_is_not_a_real_key():
    payload = json.loads(analyzer.EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert payload["api_key"] == "PASTE_OPENROUTER_API_KEY_HERE"
    assert "sk-or-v1" not in payload["api_key"]


def test_broken_json_is_reported_without_echoing_the_file(tmp_path):
    """壞掉的設定檔報錯時不能把整份內容印出來（裡面有 key）。"""
    path = tmp_path / "ai_config.local.json"
    path.write_text(f'{{"api_key": "{LOCAL_KEY}", oops', encoding="utf-8")
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.load_config(path)
    assert LOCAL_KEY not in str(excinfo.value)
    assert "不是合法 JSON" in str(excinfo.value)


def test_missing_api_key_in_config_is_reported(tmp_path):
    path = tmp_path / "ai_config.local.json"
    path.write_text(json.dumps({"model": "m:free"}), encoding="utf-8")
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.load_config(path)
    assert "缺少 api_key" in str(excinfo.value)


def test_blank_api_key_is_rejected(tmp_path):
    path = tmp_path / "ai_config.local.json"
    path.write_text(json.dumps({"api_key": "   "}), encoding="utf-8")
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.load_config(path)


def test_config_must_be_an_object(tmp_path):
    path = tmp_path / "ai_config.local.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.load_config(path)
    assert "JSON 物件" in str(excinfo.value)


# ----------------------------------------------------------------------
# 3-4. api_key 與 model 正確傳下去
# ----------------------------------------------------------------------


def test_config_key_reaches_the_provider(monkeypatch, tmp_path):
    import analyze_item as live

    seen = {}

    def fake_analyze(client, api_key, item_id, *, model, max_photos, echo):
        seen["api_key"] = api_key
        seen["model"] = model
        return []

    monkeypatch.setattr(live, "analyze", fake_analyze)
    monkeypatch.setattr(live, "load_config", lambda *a, **k: analyzer.AiConfig(api_key=LOCAL_KEY, model=analyzer.DEFAULT_MODEL))
    assert live.main(["ITM-0001"]) == 0
    assert seen["api_key"] == LOCAL_KEY
    assert seen["model"] == analyzer.DEFAULT_MODEL


def test_config_model_is_used(monkeypatch, tmp_path):
    import analyze_item as live

    seen = {}

    def fake_analyze(client, api_key, item_id, *, model, max_photos, echo):
        seen["model"] = model
        return []

    monkeypatch.setattr(live, "analyze", fake_analyze)
    monkeypatch.setattr(live, "load_config", lambda *a, **k: analyzer.AiConfig(api_key=LOCAL_KEY, model="some/model:free"))
    live.main(["ITM-0001"])
    assert seen["model"] == "some/model:free"


def test_cli_model_overrides_the_config(monkeypatch, tmp_path):
    import analyze_item as live

    seen = {}

    def fake_analyze(client, api_key, item_id, *, model, max_photos, echo):
        seen["model"] = model
        return []

    monkeypatch.setattr(live, "analyze", fake_analyze)
    monkeypatch.setattr(live, "load_config", lambda *a, **k: analyzer.AiConfig(api_key=LOCAL_KEY, model="from/config:free"))
    live.main(["ITM-0001", "--model", "from/cli:free"])
    assert seen["model"] == "from/cli:free"


def test_blank_model_uses_default(tmp_path):
    """model 沒填（缺漏或空白）就用預設值。"""
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"api_key": LOCAL_KEY, "model": "  "}),
                    encoding="utf-8")
    assert analyzer.load_config(path).model == analyzer.DEFAULT_MODEL


def test_model_of_wrong_type_is_rejected(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"api_key": LOCAL_KEY, "model": 123}), encoding="utf-8")
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.load_config(path)
    assert "model" in str(excinfo.value)
    assert LOCAL_KEY not in str(excinfo.value)


def test_missing_model_uses_default(tmp_path):
    config = analyzer.load_config(write_config(tmp_path / "c.json"))
    assert config.model == analyzer.DEFAULT_MODEL


# ----------------------------------------------------------------------
# 5. 完全脫離環境變數
# ----------------------------------------------------------------------


def test_global_env_key_is_never_read(monkeypatch, tmp_path):
    """環境變數放了錯的 key 時，adapter 必須用 local config 的。"""
    import analyze_item as live

    monkeypatch.setenv("OPENROUTER_API_KEY", GLOBAL_KEY)
    seen = {}

    def fake_analyze(client, api_key, item_id, *, model, max_photos, echo):
        seen["api_key"] = api_key
        return []

    monkeypatch.setattr(live, "analyze", fake_analyze)
    monkeypatch.setattr(live, "load_config", lambda *a, **k: analyzer.AiConfig(api_key=LOCAL_KEY, model=analyzer.DEFAULT_MODEL))

    assert live.main(["ITM-0001"]) == 0
    assert seen["api_key"] == LOCAL_KEY
    assert seen["api_key"] != GLOBAL_KEY


def test_source_does_not_read_any_environment_variable():
    """程式碼裡不能有讀環境變數的機制。

    註解和 docstring 可以提到 OPENROUTER_API_KEY（那是在說明「刻意不讀它」）。
    單獨一個環境變數名稱的字串沒有意義 —— 要真的拿到值一定得搭配
    os.environ 或 getenv，所以把字串 literal 一起排除不會漏掉真正的漏洞。
    """
    source = (TOOLS / "analyze_item.py").read_text(encoding="utf-8")
    code = _code_without_comments_or_strings(source)
    for forbidden in ("os.environ", "getenv", "OPENROUTER_API_KEY", "import os"):
        assert forbidden not in code, f"adapter 的程式碼不該出現 {forbidden}"


def _code_without_comments_or_strings(source):
    """把註解與字串 literal 換成空白，其餘原樣。"""
    pattern = re.compile(r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|(#.*$)')
    return pattern.sub(lambda m: " " * len(m.group(0)), source)


def test_no_api_key_command_line_flag():
    source = (TOOLS / "analyze_item.py").read_text(encoding="utf-8")
    assert "--api-key" not in source


def test_module_does_not_import_os():
    assert not hasattr(analyzer, "os")


# ----------------------------------------------------------------------
# 6. 真實 key 不外洩
# ----------------------------------------------------------------------


def test_config_error_never_leaks_the_key(tmp_path, capsys):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"api_key": LOCAL_KEY, "model": 123}), encoding="utf-8")
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.load_config(path)
    captured = capsys.readouterr()
    assert LOCAL_KEY not in captured.out
    assert LOCAL_KEY not in captured.err


def test_example_and_docs_contain_no_real_key():
    for name in ("ai_config.example.json",):
        assert "sk-or-v1-" not in (TOOLS / name).read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "sk-or-v1-" not in readme


# ----------------------------------------------------------------------
# 7. ai_config.local.json 必須被 gitignore
# ----------------------------------------------------------------------


def test_gitignore_covers_the_local_config():
    result = subprocess.run(
        ["git", "check-ignore", "-v", "tools/ai_config.local.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        "tools/ai_config.local.json 沒有被 gitignore —— 會被 commit！"
    )


def test_gitignore_does_not_cover_the_example():
    """example 一定要能進 Git，否則新使用者拿不到。"""
    result = subprocess.run(
        ["git", "check-ignore", "tools/ai_config.example.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode != 0, "example 不該被 gitignore"


def test_local_config_is_not_tracked():
    result = subprocess.run(
        ["git", "ls-files", "tools/"], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8",
    )
    assert "ai_config.local.json" not in result.stdout


def test_every_non_example_json_in_tools_is_gitignored():
    """tools/ 下除了 example，任何 json 都必須被 gitignore。

    使用者建立 ai_config.local.json 是正常流程，所以不能斷言檔案不存在；
    要斷言的是它永遠不會被 git 追蹤。
    """
    import subprocess as sp

    for path in sorted((ROOT / "tools").glob("*.json")):
        if path.name == "ai_config.example.json":
            continue
        relative = path.relative_to(ROOT).as_posix()
        result = sp.run(["git", "check-ignore", relative], cwd=ROOT,
                        capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, f"{path.name} 沒有被 gitignore，會被 commit！"


# ----------------------------------------------------------------------
# 8. README 有最短使用說明
# ----------------------------------------------------------------------


def test_readme_explains_first_time_setup():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "ai_config.example.json" in readme
    assert "ai_config.local.json" in readme
    assert "python tools/analyze_item.py ITM-0001" in readme
    assert "sk-or-v1-" not in readme
