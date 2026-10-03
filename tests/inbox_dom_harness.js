/* 用 node 的 vm 在假的 DOM 上跑真正的 ui/inbox.js。
 *
 * 為什麼要這樣：pytest 讀原始碼做字串比對，擋得住「忘了清 value」，
 * 擋不住「清 value 之後 FileList 被清空」這種語義錯誤 ——
 * 8d2d2b9 就是這樣壞掉的。所以這裡測行為：真的派發 change 事件，
 * 看 upload() 到底收到幾個 File。
 *
 * 假的 file input 照 HTML Standard 建模：value = "" 會清空 selected
 * files，而 files getter 在清單沒變時回傳同一個（活的）FileList 物件。
 *
 * 輸出 JSON 給 pytest 讀。執行：node tests/inbox_dom_harness.js
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const FILES = ["api.js", "inbox.js"].map((name) => ({
  name,
  source: fs.readFileSync(path.join(ROOT, "ui", name), "utf8"),
}));

/* ------------------------------------------------------------ 假的 DOM */

function fakeElement(id) {
  const listeners = {};
  const element = {
    id,
    dataset: {},
    style: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, force) { (force ? this._set.add : this._set.delete).call(this, c); },
    },
    value: "",
    hidden: false,
    disabled: false,
    textContent: "",
    innerHTML: "",
    firstChild: null,
    childNodes: [],
    addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
    appendChild(child) { this.childNodes.push(child); return child; },
    removeChild(child) { this.childNodes = this.childNodes.filter((c) => c !== child); },
    replaceChildren(...kids) { this.childNodes = kids; },
    setAttribute() {},
    removeAttribute() {},
    focus() {},
    dispatch(type, event) {
      return Promise.all((listeners[type] || []).map((fn) => fn(event)));
    },
  };
  return element;
}

/* 照規格：value = "" 清空 selected files；files getter 回傳同一個活物件 */
function makeFileInput(files) {
  const live = files;
  const listeners = {};
  return {
    clickCount: 0,
    click() { this.clickCount += 1; },
    get files() { return live; },
    get value() { return live.length ? "C:\\fakepath\\" : ""; },
    set value(v) { if (v === "") live.length = 0; },
    addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
    fireChange() { return Promise.all((listeners.change || []).map((fn) => fn())); },
  };
}

function makeDocument(fileInput) {
  const elements = new Map();
  return {
    getElementById(id) {
      if (id === "file-input") return fileInput;
      if (!elements.has(id)) elements.set(id, fakeElement(id));
      return elements.get(id);
    },
    querySelectorAll() { return []; },
    createElement(tag) { return fakeElement(tag); },
    createTextNode(text) { return { textContent: text }; },
  };
}

/* ------------------------------------------------------------- 執行 */

async function run(fileCount, label) {
  /* 用真的 File 物件：node 的 FormData 只接受 Blob/File，
     用假物件會測不到真正的 append 路徑。 */
  const files = Array.from({ length: fileCount }, (_, i) =>
    new File([`photo-${i}`], `IMG_${i}.jpg`, { type: "image/jpeg" })
  );

  const fileInput = makeFileInput(files);
  const requests = [];

  const sandbox = {
    console,
    URL,
    URLSearchParams,
    FormData,
    setTimeout: () => 0,
    clearTimeout: () => {},
    document: makeDocument(fileInput),
    window: { location: { href: "" }, history: { replaceState() {} } },
    async fetch(path, options) {
      requests.push({ path, method: (options && options.method) || "GET", options });
      const payload = path.includes("/group") ? "[]" : '{"entries":[],"count":0}';
      return { ok: true, status: 200, text: async () => payload };
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  /* 和瀏覽器一樣依序載入兩個 script：inbox.js 用到 api.js 的 showError 等 */
  for (const file of FILES) {
    vm.runInContext(file.source, sandbox, { filename: file.name });
  }

  await fileInput.fireChange();
  /* 等 upload() 的 await 鏈跑完 */
  for (let i = 0; i < 10; i += 1) await new Promise((r) => setImmediate(r));

  const upload = requests.find((r) => r.path === "/api/inbox/photos");
  const sent = upload && upload.options.body
    ? upload.options.body.getAll("files").map((f) => f.name)
    : null;

  return {
    label,
    requested: fileCount,
    posted: Boolean(upload),
    method: upload ? upload.method : null,
    fieldNames: upload && upload.options.body
      ? [...new Set(upload.options.body.keys())]
      : [],
    sentNames: sent,
    sentCount: sent ? sent.length : 0,
    fileInputCleared: fileInput.value === "",
  };
}

(async () => {
  const results = [];
  for (const count of [0, 1, 3, 8]) {
    results.push(await run(count, `${count} photos`));
  }
  process.stdout.write(JSON.stringify(results, null, 2));
})();