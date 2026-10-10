"""自主性 Live 管線驗證（Phase 2C-D 的可重複入口；取代 2C-C 的未提交驅動）。

用法：
    python tools/validate_autonomy_live.py --allow-live [--include-failure]
        [--data-dir DIR] [--max-calls 8]

安全與界線：
  - 必須加 --allow-live 才會動作；**永遠只送 `tools/eval_fixtures/images`
    的合成 fixture**，不送真實照片或使用者資料。
  - 使用專案現有的 `tools/ai_config.local.json`（provider/model/api key）；
    本工具不儲存、不列印任何憑證。
  - 呼叫數以 --max-calls 為上限（預設 8，含失敗重試）。
  - 資料根目錄預設在系統 temp 下，且只會清空「帶有本工具標記檔」的目錄；
    指向非空又沒有標記的目錄時會拒絕執行，避免誤刪。

流程（每個流程一個獨立 item，結果以 JSON 印出）：
  R  修訂：BOSE 標籤 → 分析 → 加入 SONY 標籤 → 分析
     （預期：身分被修訂，或兩個身分被升級為衝突 —— 兩者皆為合法結局，
      由 promotions 欄位呈現）
  P  保護：使用者命名＋備註 → 加收據 → 分析
     （預期：name 留待確認、購買資訊依政策自動）
  S  選擇：9 張（最早標籤＋最新收據＋雜訊）→ 分析
     （預期：身分溯源到最早標籤照片）
  F  失敗/重試（--include-failure）：無效模型 → 400；修復後重試 → 成功
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IMAGES = ROOT / "tools" / "eval_fixtures" / "images"
DEFAULT_DATA_DIR = Path(tempfile.gettempdir()) / "kilo" / "validate_autonomy_live"
MARKER = ".validate_autonomy_live"


def _prepare_data_dir(data_dir: Path) -> None:
    """清空（僅限本工具標記過的目錄或全新的目錄）並建立標記。"""
    if data_dir.exists() and any(data_dir.iterdir()):
        if not (data_dir / MARKER).exists():
            raise SystemExit(
                f"{data_dir} 不是空的且沒有本工具標記；拒絕清空。"
                " 請改用新的 --data-dir。"
            )
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / MARKER).write_text("temp data root for validate_autonomy_live\n",
                                   encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="自主性 Live 管線驗證（僅合成 fixture）",
    )
    parser.add_argument("--allow-live", action="store_true",
                        help="確認允許對設定的 provider 發出真實請求（僅合成圖）")
    parser.add_argument("--include-failure", action="store_true",
                        help="額外跑失敗/重試流程（+2 次呼叫，其中一次為無效模型 4xx）")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="隔離的資料根目錄（預設在系統 temp 下）")
    parser.add_argument("--max-calls", type=int, default=8,
                        help="provider 呼叫數上限（預設 8）")
    args = parser.parse_args(argv)

    if not args.allow_live:
        print("拒絕對外部 provider 發出請求：請加上 --allow-live（僅合成 fixture）。")
        return 2

    planned = 5 if args.include_failure else 3
    if planned > args.max_calls:
        print(f"此流程需要 {planned} 次呼叫，超過 --max-calls {args.max_calls}；中止。")
        return 2

    # 先過所有安全檢查（資料目錄）再碰設定：沒設定時也保證不會誤刪任何東西。
    _prepare_data_dir(args.data_dir)

    from shop import ai_config

    try:
        conf = ai_config.load_config()
    except Exception as exc:  # noqa: BLE001 - 沒有設定就早退，不印內容
        print(f"沒有可用的 AI 設定：{exc}")
        return 2

    from shop import config as config_mod, db as db_mod  # noqa: E402
    import shop.ai_client as ai_client  # noqa: E402
    from shop.api import create_app  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402

    cfg = config_mod.load(args.data_dir)
    db_mod.init(cfg)
    config_mod.ensure_dirs(cfg)
    client = TestClient(create_app(cfg))

    calls = {"ok": 0, "failed": 0}
    mode = {"bad_model": False}
    real_load = ai_config.load_config

    def load_with_override():
        current = real_load()
        if mode["bad_model"]:
            return dataclasses.replace(current, model="invalid-model-validate-2cd")
        return current

    ai_config.load_config = load_with_override

    def image_files(names: list[str]) -> list:
        return [("files", (name, (IMAGES / name).read_bytes(), "image/jpeg"))
                for name in names]

    def create_item(names: list[str]) -> str:
        up = client.post("/api/inbox/photos", files=image_files(names)).json()
        intake = client.post(
            "/api/inbox/intake",
            json={"files": [e["relative"] for e in up["entries"]],
                  "kind": "intake"},
        ).json()
        return intake["item_id"]

    def upload_to_item(item_id: str, names: list[str]) -> None:
        obs = client.post(f"/api/items/{item_id}/observations",
                          json={"kind": "recheck"}).json()
        res = client.post(f"/api/observations/{obs['id']}/photos",
                          files=image_files(names))
        assert res.status_code == 201, res.text

    def analyze(item_id: str) -> dict:
        r = client.post(f"/api/items/{item_id}/ai/analyze?auto=1")
        if r.status_code == 201:
            calls["ok"] += 1
            return {"status": 201, "suggestions": [
                {"field": s["field"], "value": s["value"],
                 "status": s["status"], "source": s["source"],
                 "source_photo_id": s["source_photo_id"]}
                for s in r.json()
            ]}
        calls["failed"] += 1
        try:
            return {"status": r.status_code, "detail": r.json().get("detail")}
        except Exception:  # noqa: BLE001
            return {"status": r.status_code}

    def item_state(item_id: str) -> dict:
        d = client.get(f"/api/items/{item_id}").json()
        return {
            "name": d["item"]["name"], "brand": d["item"]["brand"],
            "model": d["item"]["model"], "attributes": d["item"]["attributes"],
            "notes": d["item"]["notes"], "created_at": d["item"]["created_at"],
            "photos": len(d["photos"]),
            "suggestions": [
                {"field": s["field"], "value": s["value"],
                 "status": s["status"], "source": s["source"]}
                for s in d["suggestions"]
            ],
        }

    results: dict = {}
    print(f"== 自主性 Live 驗證：provider={conf.provider} model={conf.model} "
          f"（僅合成 fixture；上限 {args.max_calls} 次）==")

    # R：修訂（或升級為衝突）
    item_r = create_item(["label_bose.jpg"])
    first = analyze(item_r)
    upload_to_item(item_r, ["label_sony.jpg"])
    second = analyze(item_r)
    results["R_revision"] = {
        "first_analysis": first,
        "second_analysis": second,
        "item": item_state(item_r),
    }

    # P：使用者保護
    item_p = create_item(["unknown_part.jpg"])
    client.patch(f"/api/items/{item_p}",
                 json={"name": "不明金屬零件", "notes": "五金行買的，忘了名字"})
    upload_to_item(item_p, ["receipt_makita.jpg"])
    results["P_protection"] = {"analysis": analyze(item_p),
                               "item": item_state(item_p)}

    # S：九張照片選擇
    item_s = create_item(
        ["label_nikon.jpg", "receipt_strap.jpg"]
        + [f"noise_{i:02d}.jpg" for i in range(2, 9)]
    )
    before_s = client.get(f"/api/items/{item_s}").json()
    label_photo_id = before_s["photos"][0]["id"]
    analysis_s = analyze(item_s)
    suggestions_s = analysis_s.get("suggestions") or []
    identity_source = {
        s["field"]: s.get("source_photo_id") == label_photo_id
        for s in suggestions_s
        if s["field"] in ("name", "brand", "model", "identifier:serial")
    }
    results["S_selection"] = {
        "photo_count": len(before_s["photos"]),
        "identity_from_earliest_photo": identity_source,
        "analysis": analysis_s,
        "item": item_state(item_s),
    }

    # F：失敗 + 重試
    if args.include_failure:
        item_f = create_item(["unknown_part.jpg"])
        mode["bad_model"] = True
        failed = analyze(item_f)
        mode["bad_model"] = False
        photos_after_failure = len(
            client.get(f"/api/items/{item_f}").json()["photos"])
        retried = analyze(item_f)
        results["F_failure_retry"] = {
            "failure": failed,
            "photos_after_failure": photos_after_failure,
            "retry": retried,
            "item": item_state(item_f),
        }

    ai_config.load_config = real_load

    print(json.dumps({
        "provider": conf.provider,
        "model": conf.model,
        "calls": calls,
        "results": results,
    }, ensure_ascii=False, indent=1))
    print(f"完成：成功 {calls['ok']} 次、失敗 {calls['failed']} 次；"
          f"資料根目錄 {args.data_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
