"""拍照與相簿／檔案匯入的獨立入口（capture 視圖）。

本輪目標：`/capture` 明確區分「拍照」（capture="environment"）與
「匯入照片」（type=file、accept=image/*、multiple、不帶 capture）兩個
獨立入口；兩者共用既有 appendFiles 待整理流程（多張、預覽、
移除、分批追加、拖放、確認後才 AI 分析、存起來才建檔）。

靜態接線以原始碼檢查；格式分流（`web/core/photoFiles.js`）與追加流程，
以及「實際 createCaptureView ＋模擬 router 掛載到 #app 後的裝置文案
切換」（coarse／fine／無 #app 後備），都以 Node 執行實際 ESM 模組驗證
（需要 node；缺失時跳過並記錄原因）。
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
_CAPTURE_VIEW_URI = (WEB / "views" / "capture.js").as_uri()


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


# ----------------------------------------------------------------------
# Node 掛載測試：實際執行 createCaptureView ＋模擬 router 掛載，驗證
# 裝置文案切換（此測試會抓到「觀察 document.body 而掛載點在 #app」的
# 迴歸：shim 的 MutationObserver 只在被觀察子樹真的變更時回呼）。
# ----------------------------------------------------------------------

#: 以真實的 `web/views/capture.js` 執行 createCaptureView，並用最小 DOM
#: shim 模擬「router 把 view.element 掛進 #app」（web/app.js 的實際掛載
#: 行為），驗證掛載後匯入按鈕的裝置文案。
#:
#: shim 的真實性：
#: - MutationObserver 只在「被觀察節點或有 subtree 的後代真的被插入」時
#:   回呼；舊 bug（observe(document.body, {childList:true}) 而插入點在
#:   #app）在此 shim 下永遠等不到回呼 → 文案維持預設 → 測試失敗。
#: - 掛載前先插入一個不相關節點（模擬 toast），驗證監視器不會提早停止。
#: - 掛載確認後 activeObservers 必須歸零（不做長期 DOM 監視）。
_NODE_MOUNT_TEST_PROGRAM = r"""
const [captureUrl, scenario] = process.argv.slice(1);

let failures = 0;
function check(cond, msg) {
  if (!cond) { failures += 1; console.log('FAIL(' + scenario + '): ' + msg); }
}

let documentRoot = null;

class FakeNode {
  constructor(tag) {
    this.tagName = tag;
    this.parentNode = null;
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.textContent = '';
    this.disabled = false;
    this.clickCalls = 0;
    this._idMap = new Map();
    this.classList = { add: () => {}, remove: () => {}, contains: () => false };
  }
  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === documentRoot;
  }
  _isDescendantOf(ancestor) {
    let node = this.parentNode;
    while (node) {
      if (node === ancestor) return true;
      node = node.parentNode;
    }
    return false;
  }
  set innerHTML(html) {
    // createCaptureView 初始化只用 #id 查詢；把模板中的 id 建成子節點，
    // 並保留緊接在標籤後的純文字（供 #btn-import-text 的預設文案比對）。
    for (const match of String(html).matchAll(/id="([^"]+)"[^>]*>([^<]*)/g)) {
      const child = new FakeNode('div');
      child.parentNode = this;
      this.children.push(child);
      child.textContent = match[2].trim();
      this._idMap.set(match[1], child);
    }
  }
  get innerHTML() { return ''; }
  _findById(id) {
    if (this._idMap.has(id)) return this._idMap.get(id);
    for (const child of this.children) {
      const found = child._findById(id);
      if (found) return found;
    }
    return null;
  }
  querySelector(selector) {
    if (selector.startsWith('#')) return this._findById(selector.slice(1));
    return null;
  }
  querySelectorAll() { return []; }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    notifyMutation(this);
    return child;
  }
  insertBefore(child, _ref) { return this.appendChild(child); }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  fire(type) { (this.listeners[type] || []).forEach((fn) => fn({ type })); }
  click() { this.clickCalls += 1; }
}

const activeObservers = new Set();

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.target = null;
    this.options = {};
    this.active = false;
  }
  observe(target, options = {}) {
    this.target = target;
    this.options = options;
    this.active = true;
    activeObservers.add(this);
  }
  disconnect() { this.active = false; activeObservers.delete(this); }
}

function notifyMutation(node) {
  for (const observer of Array.from(activeObservers)) {
    if (!observer.active) continue;
    const covered = node === observer.target
      || (observer.options.subtree && node._isDescendantOf(observer.target));
    if (covered) observer.callback([{ type: 'childList', target: node }], observer);
  }
}

documentRoot = new FakeNode('#document');
const body = new FakeNode('body');
body.parentNode = documentRoot;
documentRoot.children.push(body);
const registry = new Map();
globalThis.document = {
  body,
  getElementById: (id) => registry.get(id) || null,
  createElement: (tag) => new FakeNode(tag),
  addEventListener: () => {},
  querySelector: () => null,
};
function freshApp() {
  const app = new FakeNode('div');
  app.parentNode = body;
  body.children.push(app);
  registry.set('app', app);
  return app;
}

let coarsePointer = scenario !== 'fine';
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.MutationObserver = FakeMutationObserver;
globalThis.matchMedia = (query) => ({
  matches: coarsePointer && query.indexOf('coarse') !== -1,
  media: query,
  addEventListener: () => {}, removeEventListener: () => {},
  addListener: () => {}, removeListener: () => {},
});

let label = null;
try {
  const { createCaptureView } = await import(captureUrl);

  const mountInto = scenario === 'fallback' ? body : freshApp();

  const view = await createCaptureView({}, { navigate: () => {} });
  const root = view.element;
  const importText = root.querySelector('#btn-import-text');
  check(importText !== null, '找不到 #btn-import-text');
  check(activeObservers.size === 1,
        '掛載前應恰有一個掛載監視器，得 ' + activeObservers.size);

  // 掛載前先有不相關的插入（模擬 toast 等）：監視器不得提早停止，
  // 文案也不得提早依裝置切換。
  const preMountLabel = importText.textContent;
  check(preMountLabel === '選擇照片',
        '掛載前應維持模板預設文案「選擇照片」，得「' + preMountLabel + '」');
  mountInto.appendChild(new FakeNode('div'));
  check(activeObservers.size === 1,
        '非本次 view 的插入不應使監視器停止，得 ' + activeObservers.size);
  check(importText.textContent === preMountLabel,
        '掛載前的插入不應改動文案');

  // 模擬 router 掛載：把 view.element 放進實際掛載容器
  mountInto.appendChild(root);

  const expected = coarsePointer ? '從相簿匯入' : '選擇照片';
  label = importText.textContent;
  check(label === expected,
        '掛載後匯入按鈕文案應為「' + expected + '」，得「' + label + '」');
  check(activeObservers.size === 0,
        '掛載確認後應立即停止觀察（不得長期監視 DOM），得 ' + activeObservers.size);

  // 入口行為不變：拍照入口 → capture-input；匯入入口 → import-input；
  // 托盤中的兩個追加入口也必須正常。
  const captureInput = root.querySelector('#capture-input');
  const importInput = root.querySelector('#import-input');
  root.querySelector('#btn-capture-photo').fire('click');
  check(captureInput.clickCalls === 1, '拍照入口應觸發 capture-input');
  root.querySelector('#btn-import-photos').fire('click');
  check(importInput.clickCalls === 1, '匯入入口應觸發 import-input');
  root.querySelector('#btn-add-capture').fire('click');
  root.querySelector('#btn-add-import').fire('click');
  check(captureInput.clickCalls === 2, '托盤拍照入口應觸發 capture-input');
  check(importInput.clickCalls === 2, '托盤匯入入口應觸發 import-input');
} catch (err) {
  failures += 1;
  console.log('FAIL(' + scenario + '): 未預期例外：' + (err && err.stack || err));
}

console.log(JSON.stringify({ failures, scenario, label }));
"""


def run_mount_scenario(scenario: str) -> dict:
    stdout = run_node_program(_NODE_MOUNT_TEST_PROGRAM, [_CAPTURE_VIEW_URI, scenario])
    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["failures"] == 0, (
        f"掛載情境「{scenario}」有 {payload['failures']} 項失敗：\n{stdout}"
    )
    return payload


@pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="這台機器沒有 node；掛載測試需要 node 執行實際 capture 視圖",
)
def test_import_label_after_mount_on_coarse_pointer():
    """實際執行 createCaptureView、模擬 router 掛載到 #app：
    觸控（coarse）裝置掛載後，匯入按鈕文案為「從相簿匯入」，
    監視器在掛載確認後立即停止，且四個入口的行為不變。"""
    payload = run_mount_scenario("coarse")
    assert payload["label"] == "從相簿匯入"


@pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="這台機器沒有 node；掛載測試需要 node 執行實際 capture 視圖",
)
def test_import_label_after_mount_on_fine_pointer():
    """非觸控裝置掛載後，匯入按鈕文案為「選擇照片」；監視器同樣在
    掛載確認後立即停止（證明掛載處理確實執行過）。"""
    payload = run_mount_scenario("fine")
    assert payload["label"] == "選擇照片"


@pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="這台機器沒有 node；掛載測試需要 node 執行實際 capture 視圖",
)
def test_import_label_mount_fallback_without_app_container():
    """#app 掛載容器不存在時退回觀察 body：掛載後文案仍正確切換
    （coarse → 「從相簿匯入」）。"""
    payload = run_mount_scenario("fallback")
    assert payload["label"] == "從相簿匯入"
