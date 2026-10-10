"""tools/validate_autonomy_live.py 的安全守門（不碰網路、不動真實資料）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_autonomy_live.py"), *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env,
    )


def test_refuses_to_call_provider_without_allow_live():
    """沒有 --allow-live 一律拒絕（exit 2），且不觸碰任何設定或資料。"""
    result = _run()
    assert result.returncode == 2
    assert "--allow-live" in result.stdout


def test_refuses_non_marked_non_empty_data_dir(tmp_path):
    """--data-dir 非空又沒有本工具標記 → 拒絕清空（不誤刪別人的目錄）。"""
    (tmp_path / "existing.txt").write_text("x", encoding="utf-8")
    result = _run("--allow-live", "--data-dir", str(tmp_path))
    assert result.returncode != 0
    assert "拒絕清空" in (result.stdout + result.stderr)
    assert (tmp_path / "existing.txt").exists()      # 原目錄毫髮無傷
