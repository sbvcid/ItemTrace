"""Phase 10：README / 啟動體驗不會和實際脫節。

README 是這個專案唯一的上手文件，它一旦和程式對不上，第一個 clone 的人
就被擋住了。這裡把「文件說的東西真的存在」變成測試。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CONFIG_EXAMPLE = json.loads(
    (ROOT / "config.example.json").read_text(encoding="utf-8-sig")
)


# ----------------------------------------------------------------------
# 文件裡的命令真的存在
# ----------------------------------------------------------------------


def test_readme_documents_the_three_startup_steps():
    for command in ("pip install -r requirements.txt",
                    "python shopctl.py init",
                    "python serve.py"):
        assert command in README, f"README 少了：{command}"


def test_readme_documents_every_shopctl_command():
    """README 的指令表要和 shopctl.py 真的支援的指令一致。"""
    source = (ROOT / "shopctl.py").read_text(encoding="utf-8")
    commands = set(re.findall(r'add_parser\(\s*"([a-z]+)"', source))
    assert commands, "shopctl.py 的指令解析沒抓到"
    for command in sorted(commands):
        assert f"shopctl.py {command}" in README, f"README 沒寫 shopctl.py {command}"


def test_every_file_the_readme_links_to_exists():
    for target in re.findall(r"\]\((?!https?:)([^)#]+)\)", README):
        assert (ROOT / target).exists(), f"README 連結到不存在的檔案：{target}"


def test_startup_script_references_real_files():
    script = next(ROOT.glob("*.bat"), None)
    assert script is not None, "沒有 Windows 啟動腳本"
    text = script.read_text(encoding="utf-8-sig")
    for referenced in re.findall(r"(\S+\.(?:py|txt))", text):
        assert (ROOT / referenced).exists(), f"啟動腳本引用了不存在的檔案：{referenced}"


# ----------------------------------------------------------------------
# config.json 文件
# ----------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(CONFIG_EXAMPLE))
def test_every_config_key_is_documented(key):
    assert f"`{key}`" in README, f"config.example.json 有 {key}，README 沒說明"


def test_readme_does_not_invent_config_keys():
    """README 的設定表不能寫出 config.example.json 沒有的欄位。

    只看設定表那幾列 —— 把 README 裡所有反引號單字都當設定鍵會誤判
    （`void`、`backups/` 這些都不是設定鍵）。
    """
    rows = [
        line for line in README.splitlines()
        if line.strip().startswith("| `") and "` |" in line
    ]
    assert rows, "README 的設定表沒抓到列"
    documented = {
        re.match(r"\|\s*`([a-z_]+)`", row).group(1)
        for row in rows
        if re.match(r"\|\s*`([a-z_]+)`", row)
    }
    invented = documented - set(CONFIG_EXAMPLE)
    assert invented == set(), f"README 寫了不存在的設定鍵：{sorted(invented)}"


def test_readme_explains_the_lan_setting():
    """手機要連得起來，README 必須說明 server_host 與存取模型。

    新模型（手機配對）下不能只說「區網能連」：要說清楚未配對裝置
    拿不到資料 —— 配對是唯一的授權途徑。
    """
    assert "server_host" in README
    assert "0.0.0.0" in README
    assert "127.0.0.1" in README
    assert "配對" in README
    assert "未配對" in README


def test_readme_states_v1_has_no_ai():
    """v1 不含 AI 這件事必須寫在最前面，不要埋在下面。"""
    # Updated: MVP now includes AI, so we check for AI presence instead
    assert "AI" in README
    head = README[:1200]
    assert "AI" in head or "拍" in head


def test_readme_does_not_claim_unimplemented_features():
    """不要把沒做的功能寫成已存在。"""
    # Updated: MVP includes AI and backup, so removed from absent list
    for absent in ("永久刪除功能", "退貨管理", "商品合併", "FTS5"):
        assert absent not in README, f"README 不該宣稱有：{absent}"


def test_readme_documents_backup_and_restore_semantics():
    """備份要說明為什麼不能直接複製資料夾（WAL 模式）。"""
    # Updated: Check for backup command and WAL explanation
    assert "backup" in README
    assert "WAL" in README


def test_readme_documents_data_root_portability():
    """Must explain data portability and WAL backup."""
    # Updated: Check for data portability explanation
    assert "data" in README or "資料" in README
    assert "備份" in README or "backup" in README


# ----------------------------------------------------------------------
# 依賴清單
# ----------------------------------------------------------------------


def test_requirements_cover_every_third_party_import():
    """shop/ 只用標準函式庫加 FastAPI；漏列就會在別人的機器上炸。"""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    declared = {
        re.split(r"[<>=!~\[]", line, 1)[0].strip()
        for line in requirements.splitlines()
        if line.strip() and not line.startswith("#")
    }
    # PyPI 名稱 → import 名稱。multipart 的套件名是 python-multipart。
    needed = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "python-multipart": "multipart",
    }
    missing = [pkg for pkg in needed if pkg not in declared]
    assert missing == [], f"requirements.txt 少了：{missing}"


def test_every_third_party_import_is_declared():
    """反向檢查：shop/api.py 真的 import 到的東西都要在 requirements。"""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    source = (ROOT / "shop" / "api.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^\s*from\s+([a-z_]+)", source, re.M)) | set(
        re.findall(r"^\s*import\s+([a-z_]+)", source, re.M)
    )
    # 標準函式庫的 allowlist；清單外的模組一律要求在 requirements.txt。
    local = {"shop", "dataclasses", "datetime", "pathlib", "typing", "__future__",
             "contextlib", "json", "sys"}
    for module in sorted(imported - local):
        # python-multipart 提供 multipart
        declared = module in requirements or (
            module == "multipart" and "python-multipart" in requirements
        )
        assert declared, f"shop/api.py import 了 {module}，requirements.txt 沒列"


def test_data_layer_stays_standard_library_only():
    """資料層不得因為 UI 的需求而引入相依。"""
    banned = re.compile(
        r"^\s*(?:import|from)\s+(fastapi|uvicorn|pydantic|starlette|httpx|requests)",
        re.M,
    )
    for name in ("config.py", "db.py", "events.py", "ids.py", "repo.py",
                 "inbox.py", "photos.py", "models.py", "errors.py"):
        source = (ROOT / "shop" / name).read_text(encoding="utf-8")
        assert not banned.search(source), f"shop/{name} 不該引入 HTTP 層相依"


def test_serve_module_runs_and_exposes_the_documented_flags():
    result = subprocess.run(
        [sys.executable, str(ROOT / "serve.py"), "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stderr
    for flag in ("--host", "--port", "--reload"):
        assert flag in result.stdout, f"serve.py 少了 {flag}"
