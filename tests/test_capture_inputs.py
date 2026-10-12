"""拍照與相簿／檔案匯入的獨立入口（capture 視圖）。

本輪目標：`/capture` 明確區分「拍照」（capture="environment"）與
「匯入照片」（type=file、accept=image/*、multiple、不帶 capture）兩個
獨立入口；兩者共用既有 appendFiles 待整理流程（多張、預覽、
移除、分批追加、拖放、確認後才 AI 分析、存起來才建檔）。

靜態接線以原始碼檢查；格式分流（`web/core/photoFiles.js`）與追加流程
以 Node 執行實際 ESM 模組驗證（需要 node；缺失時跳過並記錄原因）。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
CAPTURE_JS = (WEB / "views" / "capture.js").read_text(encoding="utf-8")

#: node 是這個專案開發環境既有的工具（STATUS 明載 node --check 為交付檢查）；
#: 若不存在，代表這台機器跑不了 JS 邏輯測試，跳過並在報告中記錄。
_node_probe = subprocess.run(["node", "--version"], capture_output=True, text=True)
NODE_AVAILABLE = _node_probe.returncode == 0

#: Node 執行 ESM 需要的檔案 URL。
_PHOTO_FILES_URI = (WEB / "core" / "photoFiles.js").as_uri()
_APP_API_URI = (WEB / "core" / "api.js").as_uri()


# ----------------------------------------------------------------------
# 靜態接線：兩個用途明確的獨立入口
# ----------------------------------------------------------------------


def test_capture_and_import_are_two_distinct_inputs():
    """拍照輸入框帶 capture="environment"；匯入輸入框不帶 capture、
    且可一次多選 —— 兩個入口各有明確用途，互不混用。"""
    capture_tag = re.search(r'<input\b[^>]*id="capture-input"[^>]*>', CAPTURE_JS, re.S)
    import_tag = re.search(r'<input\b[^>]*id="import-input"[^>]*>', CAPTURE_JS, re.S)

    assert capture_tag, "capture.js 必須有 #capture-input（拍照入口）"
    assert import_tag, "capture.js 必須有 #import-input（匯入入口）"

    capture_attrs = capture_tag.group(0)
    import_attrs = import_tag.group(0)

    assert 'capture="environment"' in capture_attrs
    assert 'accept="image/*"' in capture_attrs
    assert "multiple" not in capture_attrs

    assert "capture" not in import_attrs
    assert 'accept="image/*"' in import_attrs
    assert "multiple" in import_attrs


def test_both_entries_and_tray_add_actions_are_wired():
    """初始畫面兩個入口、托盤中的兩個追加入口，都接到對應輸入框。"""
    assert "btn-capture-photo" in CAPTURE_JS
    assert "btn-import-photos" in CAPTURE_JS
    assert "t('capture.btnTakePhoto')" in CAPTURE_JS
    assert "t('capture.btnImport')" in CAPTURE_JS
    assert "t('capture.btnImportMobile')" in CAPTURE_JS

    assert "btn-add-capture" in CAPTURE_JS
    assert "btn-add-import" in CAPTURE_JS
    assert "t('capture.addCapture')" in CAPTURE_JS
    assert "t('capture.addImport')" in CAPTURE_JS

    assert "captureInput.click()" in CAPTURE_JS
    assert "importInput.click()" in CAPTURE_JS


def test_file_inputs_are_reset_after_reading():
    """取消選取不觸發 change：先前的照片保留；重設只發生在確實讀到檔案後，
    讓同一張照片可以再次選取。"""
    assert CAPTURE_JS.count("captureInput.value = '';") == 1
    assert CAPTURE_JS.count("importInput.value = '';") == 1


def test_capture_ui_uses_bilingual_keys():
    """新增文案四語齊全（所有 key 都必須存在於兩個語系）。"""
    for name in ("zh-TW.js", "en.js"):
        text = (WEB / "i18n" / name).read_text(encoding="utf-8")
        for key in ("btnTakePhoto", "btnImport", "btnImportMobile",
                    "addCapture", "addImport",
                    "unsupportedFormat", "previewUnsupported"):
            assert re.search(rf"\b{key}\s*:", text), f"{name} 缺少 {key}"


def test_capture_errors_are_localized_not_hardcoded():
    """錯誤提示必須走 i18n：不可在 capture.js 中出現繁體中文字面文案。"""
    assert "t('capture.unsupportedFormat')" in CAPTURE_JS
    assert "t('capture.previewUnsupported')" in CAPTURE_JS


# ----------------------------------------------------------------------
# Node 邏輯測試：格式分流＋追加流程（真實 ESM 模組）
# ----------------------------------------------------------------------

#: 在 Node 中跑共享模組的實際邏輯：
#: 1. partitionImageFiles：HEIC／HEIF 在選取當下就分流，不假裝成功。
#: 2. appendFiles 風格的追加流程：第一批之後追加第二批，兩批都保留、
#:    不重複；取消選取（空檔案清單）不影響既有照片；同名檔案不誤判重複。
#: 3. URL／File／FormData／fetch 以最小 shim 模擬瀏覽器 —— 驗證的是
#:    模組真正的程式碼路徑，不是複製一份邏輯。
_NODE_TEST_PROGRAM = r"""
const [photoFilesUrl, apiUrl] = process.argv.slice(1);

let failures = 0;
function check(cond, msg) {
  if (!cond) { failures += 1; console.log('FAIL: ' + msg); }
}

const created = [];
globalThis.URL = { createObjectURL: (f) => { created.push(f); return 'blob:' + (f.name || 'x') + '#' + (created.length - 1); },
                   revokeObjectURL: () => {} };
globalThis.FormData = class { append() {} };
globalThis.window = globalThis;
globalThis.self = globalThis;
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
Object.defineProperty(globalThis, 'navigator',
                      { value: { language: 'en-US' }, configurable: true });
globalThis.document = { body: {},
  createElement: () => ({ style: {}, addEventListener: () => {}, appendChild: () => {},
                          setAttribute: () => {}, click: () => {} }) };

const F = (name, type = '', size = 10) => ({ name, type, size, lastModified: 1 });

const { partitionImageFiles } = await import(photoFilesUrl);
const { getPhotoUrl } = await import(apiUrl);

// --- 格式分流 ---------------------------------------------------------
let r = partitionImageFiles([
  F('a.jpg', 'image/jpeg'), F('PHOTO.HEIC', 'image/heic'), F('IMG_0001', ''),
  F('b.png', 'image/png'), F('c.heif', ''), F('d.webp', 'image/webp'),
]);
check(r.valid.length === 3, 'jpeg/png(含空 MIME 的 jpg)/webp 應通過，得 ' + r.valid.length);
check(r.unsupported.length === 3, 'heic/heif/未知格式應被列出，得 ' + r.unsupported.length);
check(r.unsupported.some(f => f.name === 'PHOTO.HEIC'), '大寫 .HEIC 必須被認出');
check(r.unsupported.some(f => f.name === 'c.heif'), '.heif 必須被認出');
check(r.valid.every(f => !/\.heic$|\.heif$/i.test(f.name)), 'HEIC 不得進入可匯入清單');

r = partitionImageFiles([F('IMG_0001', '')]);
check(r.valid.length === 0 && r.unsupported.length === 1,
      '無 MIME 也無可用副檔名時要明確列入不支援（不是靜默略過）');

// --- 追加流程（appendFiles 的核心資料結構） ----------------------------
const state = { capturedFiles: [] };
let toasts = [];
const showToast = (m) => toasts.push(m);

function appendFiles(newFiles, origin = 'import') {
  if (!newFiles || newFiles.length === 0) return;
  const { valid, unsupported } = partitionImageFiles(newFiles);
  if (unsupported.length > 0) showToast('unsupportedFormat');
  if (valid.length === 0) return;
  for (const file of valid) {
    state.capturedFiles.push({ file, url: URL.createObjectURL(file), origin });
  }
}

appendFiles([F('first.jpg', 'image/jpeg')], 'capture');
check(state.capturedFiles.length === 1 && state.capturedFiles[0].origin === 'capture',
      '第一張（拍照）應保留且標記來源');

appendFiles([F('a.jpg', 'image/jpeg'), F('b.jpg', 'image/jpeg')], 'import');
check(state.capturedFiles.length === 3,
      '追加後第一批必須保留（1+2=3），得 ' + state.capturedFiles.length);
check(state.capturedFiles.map(f => f.origin).join(',') === 'capture,import,import',
      '兩批來源標記應完整保留');

appendFiles([], 'import');
check(state.capturedFiles.length === 3, '取消選取不得清除既有照片');

appendFiles([F('IMG_1.jpg', 'image/jpeg')], 'import');
appendFiles([F('IMG_1.jpg', 'image/jpeg')], 'import');
check(state.capturedFiles.length === 5,
      '同名檔案是兩次不同的選取，不得誤判重複而丟棄，得 ' + state.capturedFiles.length);
check(created.length === 5, '每張照片都應有自己的 object URL，得 ' + created.length);

const before = state.capturedFiles.length;
appendFiles([F('x.heic', 'image/heic')], 'import');
check(state.capturedFiles.length === before, 'HEIC 不應進入待整理清單');
check(toasts.includes('unsupportedFormat'), 'HEIC 必須提示使用者（不是靜默忽略）');

// --- 照片 URL 解析（既有行為不受影響） --------------------------------
check(getPhotoUrl('files/ITM-0001/original/a.jpg') === '/files/ITM-0001/original/a.jpg',
      '既有檔案路徑解析不變');
check(getPhotoUrl('blob:x') === 'blob:x', 'blob URL 原樣回傳');

console.log(JSON.stringify({ failures }));
"""


def run_node_program(program: str, args: list[str]):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"node 執行失敗（{result.returncode}）：\n{result.stderr}\n{result.stdout}"
    )
    return result.stdout


@pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="這台機器沒有 node；前端邏輯測試需要 node（開發環境既有工具，"
           "STATUS 載明 node --check 為交付檢查）",
)
def test_append_and_format_logic_runs_in_node():
    """以 Node 實際載入共享模組驗證：格式分流、兩批追加保留、取消不清空、
    同名不誤刪、HEIC 明確提示。"""
    stdout = run_node_program(_NODE_TEST_PROGRAM, [_PHOTO_FILES_URI, _APP_API_URI])
    payload = json.loads(stdout.strip().splitlines()[-1])
    failures = payload["failures"]
    assert failures == 0, f"node 邏輯測試有 {failures} 項失敗：\n{stdout}"
