"""AI 評測 harness（Phase 2C-A）。

兩種模式：

  python tools/evaluate_models.py --offline
      離線重播 tools/eval_fixtures/recorded/*.json 的模型輸出，餵進與正式
      管線相同的 shop.ai_client.parse_suggestions。用途：契約回歸 ——
      契約若收緊，先前「合法」的模型輸出會在這裡變成 invalid 而擋下來。
      品質期望（expectations）只回報、不擋（--strict 可改）；缺錄製檔或
      契約回歸會以非零退出碼結束。可在 CI 跑，完全不碰網路。

  python tools/evaluate_models.py --live --allow-live [--max-calls 8]
      用目前設定的 provider/model（tools/ai_config.local.json）對
      tools/eval_fixtures/images/ 的**合成**圖片發出真實請求（只送合成
      fixture，永遠不送真實使用者資料），把原始回應寫進錄製檔，再跑同一
      組檢查。--allow-live 是刻意的第二道確認；呼叫數受 --max-calls 上限
      約束（預設 8）。注意：Google free tier 的內容可能被用於改善產品。

期望檢查的 kind 語義（scenarios.json 的 expectations[].kind）：
  field_value_contains      某固定欄位的值包含字串（ci: 不分大小寫）
  any_value_contains        任一建議值包含字串
  any_value_contains_any    任一建議值包含清單中任一字串
  any_attribute_value_contains     任一 attribute:<key> 的值包含字串
  any_attribute_value_contains_any 任一 attribute:<key> 的值包含清單任一字串
  no_field                  沒有某固定欄位的建議
  no_field_prefix           沒有以某前綴開頭的欄位建議
  no_value_contains         沒有任何建議值包含字串（＝沒有幻覺/回吐）
  no_value_contains_any     沒有任何建議值包含清單任一字串
  no_value_combines         沒有單一建議值同時包含清單所有字串（不得把矛盾併成一個值）
  has_field                 存在非空的某欄位建議
  field_has_multiple_values 某欄位出現兩種以上不同的值（跨照片矛盾聲明）
  count_at_most             建議數不超過 n
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shop import ai_client  # noqa: E402
from shop.ai_config import AiConfigError  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "eval_fixtures"


def load_scenarios(fixtures_dir: Path) -> list[dict]:
    data = json.loads((fixtures_dir / "scenarios.json").read_text(encoding="utf-8"))
    return data["scenarios"]


def _contains(haystack: str, needle: str, ci: bool) -> bool:
    if ci:
        return needle.lower() in haystack.lower()
    return needle in haystack


def evaluate_expectation(expectation: dict, suggestions: list[dict]) -> dict:
    """回傳 {expectation, passed, detail}；不拋錯、不做網路。"""
    kind = expectation["kind"]
    values = [str(s["value"]) for s in suggestions]
    ci = bool(expectation.get("ci", False))

    if kind == "field_value_contains":
        target, needle = expectation["field"], expectation["contains"]
        hit = any(
            s["field"] == target and _contains(str(s["value"]), needle, ci)
            for s in suggestions
        )
        detail = f"{target} 包含 {needle!r}"
    elif kind == "any_value_contains":
        needle = expectation["contains"]
        hit = any(_contains(v, needle, ci) for v in values)
        detail = f"任一值包含 {needle!r}"
    elif kind == "any_value_contains_any":
        needles = expectation["contains"]
        hit = any(_contains(v, n, ci) for v in values for n in needles)
        detail = f"任一值包含 {needles!r} 之一"
    elif kind == "any_attribute_value_contains":
        needle = expectation["contains"]
        hit = any(
            s["field"].startswith("attribute:")
            and _contains(str(s["value"]), needle, ci)
            for s in suggestions
        )
        detail = f"任一屬性值包含 {needle!r}"
    elif kind == "any_attribute_value_contains_any":
        needles = expectation["contains"]
        hit = any(
            s["field"].startswith("attribute:")
            and _contains(str(s["value"]), n, ci)
            for s in suggestions
            for n in needles
        )
        detail = f"任一屬性值包含 {needles!r} 之一"
    elif kind == "no_field":
        target = expectation["field"]
        hit = not any(s["field"] == target for s in suggestions)
        detail = f"沒有 {target} 建議"
    elif kind == "no_field_prefix":
        prefix = expectation["prefix"]
        hit = not any(s["field"].startswith(prefix) for s in suggestions)
        detail = f"沒有 {prefix}* 建議"
    elif kind == "no_value_contains":
        needle = expectation["contains"]
        hit = not any(_contains(v, needle, ci) for v in values)
        detail = f"沒有任何值包含 {needle!r}"
    elif kind == "no_value_contains_any":
        needles = expectation["contains"]
        hit = not any(_contains(v, n, ci) for v in values for n in needles)
        detail = f"沒有任何值包含 {needles!r} 之一"
    elif kind == "no_value_combines":
        tokens = expectation["tokens"]
        hit = not any(
            all(_contains(v, token, ci) for token in tokens) for v in values
        )
        detail = f"沒有單一值同時包含 {tokens!r}"
    elif kind == "has_field":
        target = expectation["field"]
        hit = any(
            s["field"] == target and str(s["value"]).strip()
            for s in suggestions
        )
        detail = f"有非空的 {target} 建議"
    elif kind == "field_has_multiple_values":
        target = expectation["field"]
        distinct = {str(s["value"]) for s in suggestions if s["field"] == target}
        hit = len(distinct) >= 2
        detail = f"{target} 出現兩種以上的值（實際 {len(distinct)} 種）"
    elif kind == "count_at_most":
        hit = len(suggestions) <= int(expectation["n"])
        detail = f"建議數 <= {expectation['n']}"
    else:
        raise SystemExit(f"未知的 expectation kind：{kind!r}")

    return {"expectation": expectation, "passed": bool(hit), "detail": detail}


def _parse_recorded(response_text: str, photo_count: int) -> tuple[list[dict], bool, str]:
    """用現在的契約解析錄製輸出。回傳 (parsed, valid, error)。"""
    try:
        parsed = ai_client.parse_suggestions(
            response_text,
            [{"id": f"PH{index}"} for index in range(photo_count)],
        )
        return parsed, True, ""
    except ai_client.AnalyzerError as exc:
        return [], False, str(exc)


def _print_scenario_result(scenario: dict, parsed: list[dict],
                           results: list[dict]) -> int:
    """印出單一情境結果，回傳 quality miss 數。"""
    misses = [r for r in results if not r["passed"]]
    status = "OK  " if not misses else "MISS"
    print(f"[{status}] {scenario['id']}：{scenario['title']}")
    for suggestion in parsed:
        confidence = suggestion.get("confidence")
        confidence_text = f" ({confidence:.2f})" if isinstance(confidence, (int, float)) else ""
        print(f"         → {suggestion['field']} = {suggestion['value']!r}{confidence_text}")
    if not parsed:
        print("         → （沒有建議）")
    for miss in misses:
        print(f"         ✗ 期望未達成：{miss['detail']}")
    return len(misses)


def run_offline(fixtures_dir: Path, *, strict: bool = False) -> int:
    scenarios = load_scenarios(fixtures_dir)
    recorded_dir = fixtures_dir / "recorded"
    hard_failures: list[str] = []
    quality_misses = 0

    print(f"== 離線重播：{recorded_dir} ==")
    for scenario in scenarios:
        scenario_id = scenario["id"]
        recording_path = recorded_dir / f"{scenario_id}.json"
        if not recording_path.exists():
            hard_failures.append(f"{scenario_id}: 沒有錄製檔（{recording_path.name}）")
            print(f"[FAIL] {scenario_id}: 沒有錄製檔，先跑 --live")
            continue

        recording = json.loads(recording_path.read_text(encoding="utf-8"))
        if "response_text" not in recording:
            print(f"[NOTE] {scenario_id}: 錄製的是 provider/系統錯誤："
                  f"{recording.get('error', '?')}")
            continue

        parsed, valid, error = _parse_recorded(
            recording["response_text"], len(scenario["photos"])
        )
        if valid != bool(recording.get("valid", True)):
            hard_failures.append(
                f"{scenario_id}: 契約回歸 —— 錄製時 valid="
                f"{recording.get('valid')}，現在 valid={valid}（{error}）"
            )
        if not valid:
            print(f"[FAIL] {scenario_id}: 現行契約下輸出無效：{error}")
            continue

        results = [
            evaluate_expectation(expectation, parsed)
            for expectation in scenario["expectations"]
        ]
        quality_misses += _print_scenario_result(scenario, parsed, results)

    print(f"\n離線重播完成：{len(scenarios)} 情境、"
          f"{len(hard_failures)} 契約/資料問題、{quality_misses} 個期望未達成")
    if hard_failures:
        for failure in hard_failures:
            print(f"  ! {failure}")
        return 1
    if strict and quality_misses:
        return 1
    return 0


def run_live(fixtures_dir: Path, output_dir: Path, max_calls: int,
             pause: float) -> int:
    from shop import ai_config

    scenarios = load_scenarios(fixtures_dir)
    if len(scenarios) > max_calls:
        print(f"情境數 {len(scenarios)} 超過 --max-calls {max_calls}；中止。")
        return 2

    try:
        ai = ai_config.load_config()
    except AiConfigError as exc:
        print(f"沒有可用的 AI 設定：{exc}")
        return 2

    print(f"== 即時評測：provider={ai.provider} model={ai.model} "
          f"（{len(scenarios)} 次呼叫，僅合成 fixture）==")
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().isoformat(timespec="seconds")
    quality_misses = 0
    calls = 0

    for scenario in scenarios:
        scenario_id = scenario["id"]
        data_urls = []
        for filename in scenario["photos"]:
            path = fixtures_dir / "images" / filename
            data_urls.append(ai_client.photo_data_url(path.read_bytes(), filename))

        recording: dict = {
            "scenario_id": scenario_id,
            "provider": ai.provider,
            "model": ai.model,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "photos": scenario["photos"],
            "context": scenario.get("context", ""),
        }
        parsed: list[dict] = []
        try:
            response = ai_client.call_ai_provider(
                ai.api_key, ai.model, data_urls,
                provider=ai.provider, base_url=ai.base_url,
                context=scenario.get("context", ""),
            )
            response_text = ai_client.extract_text(response, ai.api_key)
            recording["response_text"] = response_text
            parsed, valid, error = _parse_recorded(response_text, len(scenario["photos"]))
            recording["valid"] = valid
            if valid:
                recording["parsed"] = parsed
            else:
                recording["error"] = error
        except ai_client.AnalyzerError as exc:
            # ProviderError 也是 AnalyzerError：provider 層失敗照實記錄
            recording["valid"] = False
            recording["provider_error"] = True
            recording["error"] = str(exc)
        calls += 1

        (output_dir / f"{scenario_id}.json").write_text(
            json.dumps(recording, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if recording.get("provider_error"):
            print(f"[ERR ] {scenario_id}: provider 失敗：{recording['error']}")
        elif not recording.get("valid", False):
            print(f"[FAIL] {scenario_id}: 輸出不合契約：{recording.get('error')}")
        else:
            results = [
                evaluate_expectation(expectation, parsed)
                for expectation in scenario["expectations"]
            ]
            quality_misses += _print_scenario_result(scenario, parsed, results)

        if calls < len(scenarios):
            time.sleep(pause)

    summary = {
        "provider": ai.provider,
        "model": ai.model,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "calls": calls,
        "quality_misses": quality_misses,
        "note": "合成 fixture 評測；非使用者資料",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n即時評測完成：{calls} 次呼叫、{quality_misses} 個期望未達成；"
          f"錄製寫入 {output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="對設定的 provider 發出真實請求（需 --allow-live）")
    parser.add_argument("--offline", action="store_true",
                        help="離線重播錄製輸出（預設模式；可明確指定）")
    parser.add_argument("--allow-live", action="store_true",
                        help="確認已了解會使用外部 provider（僅合成 fixture）")
    parser.add_argument("--max-calls", type=int, default=8,
                        help="即時模式的呼叫數上限（預設 8）")
    parser.add_argument("--pause", type=float, default=1.2,
                        help="即時模式每次呼叫之間的等待秒數")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES_DIR)
    parser.add_argument("--output", type=Path, default=None,
                        help="即時模式錄製輸出目錄（預設 fixtures/recorded）")
    parser.add_argument("--strict", action="store_true",
                        help="離線模式：任何期望未達成就回非零")
    args = parser.parse_args(argv)

    if args.live and args.offline:
        parser.error("--live 與 --offline 只能二選一")
    if args.live:
        if not args.allow_live:
            print("拒絕對外部 provider 發出請求：請加上 --allow-live。")
            return 2
        output = args.output or (args.fixtures / "recorded")
        return run_live(args.fixtures, output, args.max_calls, args.pause)
    return run_offline(args.fixtures, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
