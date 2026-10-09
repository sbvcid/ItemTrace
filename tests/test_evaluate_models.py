"""tools/evaluate_models.py 的離線測試。不碰網路、不動資料庫。

真實模型的品質結果見 docs/engineering/AI-EVALUATION-REPORT.md；
這裡只釘住 harness 機制與契約回歸守門：
  - 每個情境都有錄製檔，且每一筆在「現行契約」下仍合法
  - 離線重播可以完整跑完（exit 0）
  - 即時模式必須有 --allow-live 才會對外發出請求
  - 期望檢查的 kind 語義正確
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools" / "eval_fixtures"

SPEC = importlib.util.spec_from_file_location(
    "evaluate_models", ROOT / "tools" / "evaluate_models.py"
)
harness = importlib.util.module_from_spec(SPEC)
sys.modules["evaluate_models"] = harness
SPEC.loader.exec_module(harness)


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "evaluate_models.py"), *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env,
    )


def test_every_scenario_has_a_recording():
    scenarios = harness.load_scenarios(FIXTURES)
    assert len(scenarios) >= 7
    for scenario in scenarios:
        path = FIXTURES / "recorded" / f"{scenario['id']}.json"
        assert path.exists(), f"{scenario['id']} 沒有錄製檔"


def test_all_recorded_images_exist():
    for scenario in harness.load_scenarios(FIXTURES):
        for filename in scenario["photos"]:
            assert (FIXTURES / "images" / filename).exists(), filename


def test_recorded_outputs_still_parse_under_the_current_contract():
    """契約回歸守門：真實模型先前輸出的合法結果，現在也必須合法。"""
    for scenario in harness.load_scenarios(FIXTURES):
        recording = json.loads(
            (FIXTURES / "recorded" / f"{scenario['id']}.json").read_text(encoding="utf-8")
        )
        assert recording.get("valid") is True, recording.get("error")
        parsed, valid, error = harness._parse_recorded(
            recording["response_text"], len(scenario["photos"])
        )
        assert valid, f"{scenario['id']} 契約回歸：{error}"
        # 空陣列是合法結果（證據不足時的正確行為），不要求非空。
        assert isinstance(parsed, list)


def test_offline_replay_cli_runs_clean():
    result = _run_cli("--offline")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 契約/資料問題" in result.stdout


def test_live_mode_requires_the_second_confirmation():
    result = _run_cli("--live")
    assert result.returncode == 2
    assert "--allow-live" in result.stdout


def test_expectation_kinds_semantics():
    suggestions = [
        {"field": "brand", "value": "SONY"},
        {"field": "attribute:vendor", "value": "光華商場"},
    ]
    assert harness.evaluate_expectation(
        {"kind": "field_value_contains", "field": "brand",
         "contains": "sony", "ci": True}, suggestions)["passed"]
    assert harness.evaluate_expectation(
        {"kind": "any_value_contains", "contains": "SONY"}, suggestions)["passed"]
    assert harness.evaluate_expectation(
        {"kind": "any_attribute_value_contains",
         "contains": "光華"}, suggestions)["passed"]
    assert harness.evaluate_expectation(
        {"kind": "no_field", "field": "model"}, suggestions)["passed"]
    assert not harness.evaluate_expectation(
        {"kind": "no_field", "field": "brand"}, suggestions)["passed"]
    assert harness.evaluate_expectation(
        {"kind": "no_value_contains", "contains": "TOSHIBA",
         "ci": True}, suggestions)["passed"]
    assert harness.evaluate_expectation(
        {"kind": "no_value_combines", "tokens": ["sony", "toshiba"],
         "ci": True}, suggestions)["passed"]
    assert harness.evaluate_expectation(
        {"kind": "count_at_most", "n": 2}, suggestions)["passed"]
    assert not harness.evaluate_expectation(
        {"kind": "count_at_most", "n": 1}, suggestions)["passed"]


def test_unknown_expectation_kind_is_rejected():
    with pytest.raises(SystemExit):
        harness.evaluate_expectation({"kind": "nonsense"}, [])
