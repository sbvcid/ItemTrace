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
    且可一次多選 —— 兩個入口各有明確用途，互不混用。
    accept 明確包含 .heic／.heif：桌面照片選擇器光靠 image/* 不會
    顯示 iPhone 的 HEIC。"""
    capture_tag = re.search(r'<input\b[^>]*id="capture-input"[^>]*>', CAPTURE_JS, re.S)
    import_tag = re.search(r'<input\b[^>]*id="import-input"[^>]*>', CAPTURE_JS, re.S)

    assert capture_tag, "capture.js 必須有 #capture-input（拍照入口）"
    assert import_tag, "capture.js 必須有 #import-input（匯入入口）"

    capture_attrs = capture_tag.group(0)
    import_attrs = import_tag.group(0)

    assert 'capture="environment"' in capture_attrs
    assert 'accept="image/*,.heic,.heif"' in capture_attrs
    assert "multiple" not in capture_attrs

    assert "capture=" not in import_attrs
    assert 'accept="image/*,.heic,.heif"' in import_attrs
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
                    "unsupportedFormat", "previewUnsupported",
                    "heicPreviewFailed"):
            assert re.search(rf"\b{key}\s*:", text), f"{name} 缺少 {key}"


def test_capture_errors_are_localized_not_hardcoded():
    """錯誤提示必須走 i18n：不可在 capture.js 中出現繁體中文字面文案。"""
    assert "t('capture.unsupportedFormat')" in CAPTURE_JS
    assert "t('capture.previewUnsupported')" in CAPTURE_JS
    assert "t('capture.heicPreviewFailed'" in CAPTURE_JS


def test_heic_preview_goes_through_protected_api_not_local_transcoding():
    """HEIC／HEIF 的預覽必須透過受保護的本機 API（原始 File 保留給
    正式上傳），不得引入前端轉檔函式庫、也不得在選取時靜默丟棄。"""
    assert "isHeicImageFile" in CAPTURE_JS
    assert "api.previewInboxPhoto(file)" in CAPTURE_JS
    assert "URL.createObjectURL(blob)" in CAPTURE_JS
    # 不引入任何前端影像函式庫（本專案零建置、零外部腳本）。
    assert not re.search(r"heic2any|libheif|createImageBitmap\(.*heic", CAPTURE_JS)


# ----------------------------------------------------------------------
# Node 邏輯測試：格式分流＋追加流程（真實 ESM 模組）
# ----------------------------------------------------------------------

#: 在 Node 中跑共享模組的實際邏輯：
#: 1. partitionImageFiles：HEIC／HEIF 現在算「可匯入」（仍需要伺服器
#:    JPEG 預覽，capture.js 負責）；未知格式明確列入不支援。
#: 2. URL 解析 helpers：HEIC 走 /api/photos/{id}/preview、其他格式維
#:    持 /files；列表縮圖用 thumbnail_id。
#: 3. URL／File 以最小 shim 模擬瀏覽器 —— 驗證的是模組真正的程式碼
#:    路徑，不是複製一份邏輯。
_NODE_TEST_PROGRAM = r"""
const [photoFilesUrl, apiUrl] = process.argv.slice(1);

let failures = 0;
function check(cond, msg) {
  if (!cond) { failures += 1; console.log('FAIL: ' + msg); }
}

globalThis.window = globalThis;
globalThis.self = globalThis;
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
Object.defineProperty(globalThis, 'navigator',
                      { value: { language: 'en-US' }, configurable: true });

const F = (name, type = '', size = 10) => ({ name, type, size, lastModified: 1 });

const { partitionImageFiles, isHeicImageFile } = await import(photoFilesUrl);
const { getPhotoUrl, getPhotoPreviewUrl, getItemThumbnailUrl, isHeicPath } = await import(apiUrl);

// --- 格式分流：HEIC／HEIF 不再是「不支援」 ------------------------------
let r = partitionImageFiles([
  F('a.jpg', 'image/jpeg'), F('PHOTO.HEIC', 'image/heic'), F('IMG_0001', ''),
  F('b.png', 'image/png'), F('c.heif', ''), F('d.webp', 'image/webp'),
]);
check(r.valid.length === 5, 'jpeg/heic/heif/png/webp 應通過，得 ' + r.valid.length);
check(r.unsupported.length === 1, '無 MIME 且無副檔名應列入不支援，得 ' + r.unsupported.length);
check(r.valid.some(f => f.name === 'PHOTO.HEIC'), '大寫 .HEIC 必須被接受');
check(r.valid.some(f => f.name === 'c.heif'), '空 MIME 的 .heif 必須被接受');
check(!r.unsupported.some(f => /\.heic|\.heif/i.test(f.name)), 'HEIC／HEIF 不得再被拒收');

r = partitionImageFiles([F('IMG_0001', '')]);
check(r.valid.length === 0 && r.unsupported.length === 1,
      '無 MIME 也無可用副檔名時要明確列入不支援（不是靜默略過）');

check(isHeicImageFile(F('x.HEIC', '')) === true, 'isHeicImageFile：副檔名（不分大小寫）');
check(isHeicImageFile(F('x', 'image/heif')) === true, 'isHeicImageFile：MIME');
check(isHeicImageFile(F('x.jpg', 'image/jpeg')) === false, 'isHeicImageFile：JPEG 不是 HEIC');

// --- 照片 URL 解析 -------------------------------------------------------
check(getPhotoUrl('files/ITM-0001/original/a.jpg') === '/files/ITM-0001/original/a.jpg',
      '既有檔案路徑解析不變');
check(getPhotoUrl('blob:x') === 'blob:x', 'blob URL 原樣回傳');
check(isHeicPath('a.heic') && isHeicPath('B.HEIF') && !isHeicPath('a.jpg'),
      'isHeicPath 大小寫與非 HEIC');
check(getPhotoPreviewUrl({ id: 'PH-1', filename: 'files/ITM-1/original/a.heic' })
        === '/api/photos/PH-1/preview',
      'HEIC 照片走伺服器預覽端點');
check(getPhotoPreviewUrl({ id: 'PH-2', filename: 'files/ITM-1/original/a.jpg' })
        === '/files/ITM-1/original/a.jpg',
      'JPEG 照片維持原本 /files 路徑');
check(getItemThumbnailUrl({ thumbnail: 'files/ITM-1/original/a.heic', thumbnail_id: 'PH-1' })
        === '/api/photos/PH-1/preview',
      'HEIC 縮圖用 thumbnail_id 走預覽端點');
check(getItemThumbnailUrl({ thumbnail: 'files/ITM-1/original/a.jpg', thumbnail_id: 'PH-2' })
        === '/files/ITM-1/original/a.jpg',
      'JPEG 縮圖維持原檔');
check(getItemThumbnailUrl({ thumbnail: null, thumbnail_id: null }) === '',
      '沒有縮圖回空字串');

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
def test_partition_and_url_logic_runs_in_node():
    """以 Node 實際載入共享模組驗證：HEIC／HEIF 可匯入、未知格式明確
    分流、照片與縮圖 URL 解析（HEIC → 預覽端點）。"""
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


# ----------------------------------------------------------------------
# Node 流程測試：實際執行 createCaptureView，對 #import-input 觸發
# change 事件，驗證 HEIC／HEIF 的伺服器預覽流程（成功、失敗、等待中）。
# ----------------------------------------------------------------------

#: 與掛載測試同一套 DOM shim，但補上 renderTray 需要的查詢能力：
#: querySelector('img')／('.tray-item-remove')、querySelectorAll('.tray-item')、
#: element.remove()。fetch 依情境回應 /api/inbox/preview：
#: - ok：回 200 + blob → 檔案進托盤（縮圖 URL 來自伺服器 JPEG）
#: - fail：回 400 → 檔案不進托盤、toast 明確提示（不靜默丟棄）
#: - pending：永不立即回應 → 「AI 開始整理」在預覽完成前必須停用，
#:   完成後恢復（避免預覽中的檔案被上傳流程漏掉）
_NODE_HEIC_FLOW_PROGRAM = r"""
const [captureUrl, scenario] = process.argv.slice(1);

let failures = 0;
function check(cond, msg) {
  if (!cond) { failures += 1; console.log('FAIL(' + scenario + '): ' + msg); }
}
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

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
    this.files = null;
    this.value = '';
    this.className = '';
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
  remove() {
    if (this.parentNode) {
      this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
    }
  }
  set innerHTML(html) {
    const text = String(html);
    for (const match of text.matchAll(/id="([^"]+)"[^>]*>([^<]*)/g)) {
      const child = new FakeNode('div');
      child.parentNode = this;
      this.children.push(child);
      child.textContent = match[2].trim();
      this._idMap.set(match[1], child);
    }
    // renderTray 的縮圖項：<img> 與移除按鈕（querySelector 用得到）。
    for (const _ of text.matchAll(/<img\b[^>]*>/g)) {
      const child = new FakeNode('img');
      child.parentNode = this;
      this.children.push(child);
    }
    for (const match of text.matchAll(/<button\b[^>]*class="([^"]*)"[^>]*>/g)) {
      const child = new FakeNode('button');
      child.parentNode = this;
      child.className = match[1];
      this.children.push(child);
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
  _findByClass(cls) {
    for (const child of this.children) {
      if (String(child.className).split(/\s+/).includes(cls)) return child;
      const found = child._findByClass(cls);
      if (found) return found;
    }
    return null;
  }
  querySelector(selector) {
    if (selector.startsWith('#')) return this._findById(selector.slice(1));
    if (selector.startsWith('.')) return this._findByClass(selector.slice(1));
    return this.children.find((child) => child.tagName === selector) || null;
  }
  querySelectorAll(selector) {
    if (!selector.startsWith('.')) return [];
    const cls = selector.slice(1);
    const out = [];
    const walk = (node) => {
      for (const child of node.children) {
        if (String(child.className).split(/\s+/).includes(cls)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    notifyMutation(this);
    return child;
  }
  insertBefore(child) { return this.appendChild(child); }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  fire(type) {
    (this.listeners[type] || []).forEach((fn) => fn({
      type, preventDefault: () => {}, stopPropagation: () => {},
    }));
  }
  click() { this.clickCalls = (this.clickCalls || 0) + 1; }
}

const activeObservers = new Set();
class FakeMutationObserver {
  constructor(callback) { this.callback = callback; this.active = false; }
  observe(target, options = {}) { this.target = target; this.options = options; this.active = true; activeObservers.add(this); }
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
const toastContainer = new FakeNode('div');
toastContainer.parentNode = body;
body.children.push(toastContainer);
const registry = new Map([['toast-container', toastContainer]]);
globalThis.document = {
  body,
  getElementById: (id) => registry.get(id) || null,
  createElement: (tag) => new FakeNode(tag),
  addEventListener: () => {},
  querySelector: () => null,
};
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.MutationObserver = FakeMutationObserver;
globalThis.matchMedia = (query) => ({
  matches: false, media: query,
  addEventListener: () => {}, removeEventListener: () => {},
  addListener: () => {}, removeListener: () => {},
});

const created = [];
globalThis.URL = {
  createObjectURL: (blob) => { created.push(blob); return 'blob:' + created.length; },
  revokeObjectURL: () => {},
};
globalThis.FormData = class { append() {} };
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
Object.defineProperty(globalThis, 'navigator',
                      { value: { language: 'en-US' }, configurable: true });

let resolvePending = null;
const fetchCalls = [];
globalThis.fetch = async (url) => {
  const target = String(url);
  fetchCalls.push(target);
  if (target.includes('/api/inbox/preview')) {
    if (scenario === 'fail') {
      return { ok: false, status: 400, json: async () => ({ detail: 'cannot decode' }) };
    }
    if (scenario === 'pending') {
      return await new Promise((resolve) => { resolvePending = resolve; });
    }
    return { ok: true, status: 200, blob: async () => ({ preview: true }) };
  }
  return { ok: true, status: 200, json: async () => ({}) };
};

try {
  const { createCaptureView } = await import(captureUrl);
  const view = await createCaptureView({}, { navigate: () => {} });
  const root = view.element;
  body.appendChild(root);  // 模擬 router 掛載

  const importInput = root.querySelector('#import-input');
  const trayGrid = root.querySelector('#tray-grid');
  const startBtn = root.querySelector('#btn-start-organize');

  // JPEG 走既有本機流程：不呼叫伺服器預覽。
  importInput.files = [{ name: 'a.jpg', type: 'image/jpeg', size: 10 }];
  importInput.fire('change');
  await flush();
  await flush();
  check(fetchCalls.filter((u) => u.includes('/api/inbox/preview')).length === 0,
        'JPEG 不應呼叫伺服器預覽，得 ' + JSON.stringify(fetchCalls));
  check(trayGrid.querySelectorAll('.tray-item').length === 1,
        'JPEG 應直接進托盤，得 ' + trayGrid.querySelectorAll('.tray-item').length);

  // HEIC：先經伺服器 JPEG 預覽；原始 File 保留（url 是預覽 blob）。
  importInput.files = [{ name: 'IMG_0001.HEIC', type: 'image/heic', size: 20 }];
  importInput.fire('change');

  if (scenario === 'pending') {
    await flush();
    check(startBtn.disabled === true,
          '預覽等待中「AI 開始整理」必須停用（避免漏掉這張照片）');
    check(trayGrid.querySelectorAll('.tray-item').length === 1,
          '預覽完成前 HEIC 不進托盤，得 ' + trayGrid.querySelectorAll('.tray-item').length);
    resolvePending({ ok: true, status: 200, blob: async () => ({ preview: true }) });
  }
  await flush();
  await flush();

  const previewCalls = fetchCalls.filter((u) => u.includes('/api/inbox/preview'));
  const items = trayGrid.querySelectorAll('.tray-item');

  if (scenario === 'fail') {
    check(previewCalls.length === 1, 'HEIC 應嘗試伺服器預覽一次');
    check(items.length === 1,
          '預覽失敗的 HEIC 不得進入待整理清單（托盤仍只有 JPEG），得 ' + items.length);
    const toastText = toastContainer.children.map((c) => c.textContent).join(' | ');
    check(toastText.includes('IMG_0001.HEIC'),
          '預覽失敗必須明確提示檔名（不是靜默丟棄），得「' + toastText + '」');
    check(startBtn.disabled === false, '失敗後不得卡住「AI 開始整理」');
  } else {
    check(previewCalls.length === 1, 'HEIC 應呼叫伺服器預覽一次，得 ' + previewCalls.length);
    check(items.length === 2,
          'HEIC 成功取得預覽後應進托盤，得 ' + items.length);
    check(created.length >= 1, '托盤縮圖 URL 應來自伺服器預覽 blob');
    if (scenario === 'pending') {
      check(startBtn.disabled === false, '預覽完成後「AI 開始整理」應恢復可用');
    }
  }

  // 移除：按 ✕ 只移除該項，JPEG 仍在。
  if (items.length > 0) {
    const removeBtn = items[items.length - 1].querySelector('.tray-item-remove');
    check(removeBtn !== null, '托盤項必須有移除按鈕');
    removeBtn.fire('click');
    check(trayGrid.querySelectorAll('.tray-item').length === items.length - 1,
          '移除後托盤數量應減一');
  }
} catch (err) {
  failures += 1;
  console.log('FAIL(' + scenario + '): 未預期例外：' + (err && err.stack || err));
}

console.log(JSON.stringify({ failures, scenario }));
"""


def run_heic_flow_scenario(scenario: str) -> dict:
    stdout = run_node_program(_NODE_HEIC_FLOW_PROGRAM, [_CAPTURE_VIEW_URI, scenario])
    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["failures"] == 0, (
        f"HEIC 流程情境「{scenario}」有 {payload['failures']} 項失敗：\n{stdout}"
    )
    return payload


@pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="這台機器沒有 node；流程測試需要 node 執行實際 capture 視圖",
)
def test_heic_preview_flow_adds_photo_via_server_preview():
    """實際執行 createCaptureView：JPEG 不呼叫伺服器；HEIC 經
    /api/inbox/preview 取得 JPEG 預覽後進托盤，可移除。"""
    payload = run_heic_flow_scenario("ok")
    assert payload["scenario"] == "ok"


@pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="這台機器沒有 node；流程測試需要 node 執行實際 capture 視圖",
)
def test_heic_preview_failure_blocks_file_with_localized_toast():
    """預覽失敗（400）：該 HEIC 不得進入待整理清單，toast 明確顯示
    檔名（不是靜默丟棄、不假裝支援）。"""
    payload = run_heic_flow_scenario("fail")
    assert payload["scenario"] == "fail"


@pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="這台機器沒有 node；流程測試需要 node 執行實際 capture 視圖",
)
def test_start_disabled_while_heic_preview_pending():
    """伺服器預覽還在飛行時，「AI 開始整理」必須停用；完成後恢復，
    照片確實進托盤（不會被上傳流程漏掉）。"""
    payload = run_heic_flow_scenario("pending")
    assert payload["scenario"] == "pending"
