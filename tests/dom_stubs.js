/* 給 ui/*.js 行為測試用的假 DOM（tests/*_dom_harness.js 共用）。
 *
 * 只做到「ui/ 真正會用到的東西」：不模擬版面、不模擬事件傳播，
 * 重點是讓 el() / appendChild / addEventListener 能真的跑起來，
 * 這樣 renderEvents 之類的純函式有錯誤就會真的浮出來。
 */

const vm = require("vm");
const fs = require("fs");
const path = require("path");

const UI_DIR = path.resolve(__dirname, "..", "ui");

function loadScripts(names) {
  return names.map((name) => ({
    name,
    source: fs.readFileSync(path.join(UI_DIR, name), "utf8"),
  }));
}

function fakeElement(id) {
  const listeners = {};
  const classNames = new Set();
  const element = {
    id,
    dataset: {},
    style: {},
    classList: {
      _set: classNames,
      add(c) { classNames.add(c); },
      remove(c) { classNames.delete(c); },
      contains(c) { return classNames.has(c); },
      toggle(c, force) { (force ? classNames.add : classNames.delete).call(this, c); },
    },
    value: "",
    hidden: false,
    disabled: false,
    textContent: "",
    innerHTML: "",
    firstChild: null,
    childNodes: [],
    listeners,
    addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
    appendChild(child) { this.childNodes.push(child); return child; },
    removeChild(child) { this.childNodes = this.childNodes.filter((c) => c !== child); },
    replaceChildren(...kids) { this.childNodes = kids; },
    setAttribute() {},
    removeAttribute() {},
    focus() {},
    querySelectorAll() { return []; },
    /* 遞迴收集某個 class 的節點數，用來數「渲染出幾列」 */
    countClass(name) {
      let total = this.classList.contains(name) ? 1 : 0;
      for (const child of this.childNodes) {
        if (child && typeof child.countClass === "function") total += child.countClass(name);
      }
      return total;
    },
    findById(id) {
      if (this.id === id) return this;
      for (const child of this.childNodes) {
        if (child && typeof child.findById === "function") {
          const hit = child.findById(id);
          if (hit) return hit;
        }
      }
      return null;
    },
    fire(type, event) {
      return Promise.all((listeners[type] || []).map((fn) => fn(event)));
    },
  };
  /* el() 是用 node.className = value 設 class 的，classList.contains()
     必須看得見，才算得出「渲染出幾列」。 */
  Object.defineProperty(element, "className", {
    get() { return [...classNames].join(" "); },
    set(value) {
      classNames.clear();
      String(value || "").split(/\s+/).filter(Boolean).forEach((c) => classNames.add(c));
    },
    configurable: true,
  });
  return element;
}

/* 照 HTML Standard：value = "" 清空 selected files，
   files getter 在清單沒改變時回傳同一個（活的）FileList 物件。 */
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

function makeDocument(overrides = {}) {
  const elements = new Map();
  const selectors = new Map();
  return {
    getElementById(id) {
      if (overrides[id]) return overrides[id];
      if (!elements.has(id)) elements.set(id, fakeElement(id));
      return elements.get(id);
    },
    /* item.js 用它拿表格的 tbody：回一個穩定的假元素即可 */
    querySelector(selector) {
      if (!selectors.has(selector)) selectors.set(selector, fakeElement(selector));
      return selectors.get(selector);
    },
    querySelectorAll() { return []; },
    createElement(tag) { return fakeElement(tag); },
    createTextNode(text) { return { textContent: text }; },
  };
}

/* 跑一組 ui script，回傳 {sandbox, element(id), flush()} */
function mount({ scripts, documentOverrides = {}, windowProps = {}, fetchImpl }) {
  const document = makeDocument(documentOverrides);
  const sandbox = {
    console,
    URL,
    URLSearchParams,
    FormData,
    File,
    setTimeout: () => 0,
    clearTimeout: () => {},
    document,
    window: Object.assign({ location: { href: "", pathname: "/items" },
                             history: { replaceState() {} } }, windowProps),
    fetch: fetchImpl || (async () => ({ ok: true, status: 200, text: async () => "{}" })),
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const file of loadScripts(scripts)) {
    vm.runInContext(file.source, sandbox, { filename: file.name });
  }
  return {
    sandbox,
    element: (id) => document.getElementById(id),
    /* 等 await 鏈跑完（fetch 回傳的 promise 都已 resolve） */
    async flush(times = 12) {
      for (let i = 0; i < times; i += 1) await new Promise((r) => setImmediate(r));
    },
  };
}

module.exports = { fakeElement, makeFileInput, makeDocument, mount, loadScripts };