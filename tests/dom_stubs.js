/* 給 ui/*.js 行為測試用的假 DOM（tests/*_dom_harness.js 共用）。
 *
 * 只做到「ui/ 真正會用到的東西」：不模擬版面、不模擬事件傳播，
 * 重點是讓 el() / appendChild / querySelector / addEventListener 能真的
 * 跑起來，這樣 renderEvents、decide() 之類的純邏輯有錯誤就會浮出來。
 *
 * 選擇器支援：tag、.class、[attr="value"]、以及空格後代。沒有做完整的
 * CSS selector engine —— ui/ 只用到這些形式。
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

function descendants(root, out = []) {
  for (const child of root.childNodes || []) {
    if (!child || typeof child !== "object") continue;
    out.push(child);
    descendants(child, out);
  }
  return out;
}

function matchCompound(node, part) {
  const parsed = part.match(/^([a-zA-Z]*)((?:\.[\w-]+|\[[^\]]+\])*)$/);
  if (!parsed) return false;
  /* 文字節點沒有 classList / dataset，永遠不匹配任何選擇器 */
  if (!node || typeof node !== "object" || !node.classList || !node.dataset) return false;
  const [, tag, rest] = parsed;
  if (tag && String(node.tagName || "").toUpperCase() !== tag.toUpperCase()) {
    return false;
  }
  for (const token of rest.match(/\.[\w-]+|\[[^\]]+\]/g) || []) {
    if (token.startsWith(".")) {
      if (!node.classList.contains(token.slice(1))) return false;
    } else {
      const attr = token.slice(1, -1).match(/^([\w-]+)=["']?([^"']*)["']?$/);
      if (!attr) return false;
      /* 用原始屬性名比對：dataset 存的是 camelCase，key 對不起來 */
      const actual = typeof node.getAttribute === "function"
        ? node.getAttribute(attr[1]) : null;
      if (actual !== attr[2]) return false;
    }
  }
  return true
}

function queryTree(root, selector) {
  const parts = selector.trim().split(/\s+/);
  let nodes = [root, ...descendants(root)];
  for (let index = 0; index < parts.length; index += 1) {
    const part = parts[index];
    const isLast = index === parts.length - 1;
    nodes = nodes.filter((node) => {
      if (!matchCompound(node, part)) return false;
      if (isLast) return true;
      let parent = node.parentNode;
      while (parent) {
        if (matchCompound(parent, part)) return true;
        parent = parent.parentNode;
      }
      return false;
    });
  }
  return nodes.filter((node) => node !== root);
}

function fakeElement(id, tagName = "div") {
  const listeners = {};
  const classNames = new Set();
  const attributes = {};
  const ownText = { value: "" };
  const element = {
    id,
    tagName,
    dataset: {},
    style: {},
    attributes,
    childNodes: [],
    parentNode: null,
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
    innerHTML: "",
    listeners,
    addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
    appendChild(child) {
      if (child && typeof child === "object") child.parentNode = element;
      element.childNodes.push(child);
      return child;
    },
    removeChild(child) {
      element.childNodes = element.childNodes.filter((c) => c !== child);
      return child;
    },
    replaceChildren(...kids) {
      kids.forEach((kid) => { if (kid && typeof kid === "object") kid.parentNode = element; });
      element.childNodes = kids;
    },
    /* el() 把 data-* 和 href 都送進來 setAttribute，不是直接賦值 */
    setAttribute(name, value) {
      attributes[name] = String(value);
      if (name.startsWith("data-")) {
        const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        element.dataset[key] = String(value);
      }
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attributes, name)
        ? attributes[name] : null;
    },
    removeAttribute(name) { delete attributes[name]; },
    focus() {},
    querySelector(selector) { return queryTree(element, selector)[0] || null; },
    querySelectorAll(selector) { return queryTree(element, selector); },
    /* 遞迴收集某個 class 的節點數 */
    countClass(name) {
      let total = classNames.has(name) ? 1 : 0;
      for (const child of element.childNodes) {
        if (child && typeof child.countClass === "function") {
          total += child.countClass(name);
        }
      }
      return total;
    },
    allByText(text) {
      const found = [];
      if (element.textContent === text) found.push(element);
      for (const child of descendants(element)) {
        if (child.textContent === text) found.push(child);
      }
      return found;
    },
    fire(type, event) {
      return Promise.all((listeners[type] || []).map((fn) => fn(event)));
    },
  };
  /* 真 DOM 的 textContent 會把子節點的文字串起來；很多 UI 邏輯靠這個。
     firstChild 也必須跟著 childNodes 走 —— api.js 的 clear() 是
     `while (node.firstChild) node.removeChild(node.firstChild)`，
     firstChild 不動的話 clear() 會變成什麼都不做。 */
  Object.defineProperty(element, "firstChild", {
    get() { return element.childNodes[0] || null; },
    configurable: true,
  });
  Object.defineProperty(element, "textContent", {
    get() {
      return ownText.value + element.childNodes
        .map((child) => (child && typeof child.textContent === "string")
          ? child.textContent : "")
        .join("");
    },
    set(value) {
      ownText.value = String(value);
      element.childNodes = [];
    },
    configurable: true,
  });
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
    /* 先在真的假樹上找；找不到才回一個穩定的假元素，讓 item.js 掛表格
       tbody 的 rows 也有地方放（假 DOM 裡沒有真的 table）。 */
    querySelector(selector) {
      for (const root of elements.values()) {
        const found = queryTree(root, selector);
        if (found.length) return found[0];
      }
      if (!selectors.has(selector)) selectors.set(selector, fakeElement(selector));
      return selectors.get(selector);
    },
    querySelectorAll() { return []; },
    createElement(tag) { return fakeElement("", tag); },
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
    window: Object.assign(
      { location: { href: "", pathname: "/items" }, history: { replaceState() {} } },
      windowProps
    ),
    fetch: fetchImpl || (async () => ({ ok: true, status: 200, text: async () => "{}" })),
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const file of loadScripts(scripts)) {
    vm.runInContext(file.source, sandbox, { filename: file.name });
  }
  return {
    sandbox,
    document,
    element: (id) => document.getElementById(id),
    query: (selector) => document.querySelector(selector),
    /* 等 await 鏈跑完（fetch 回傳的 promise 都已 resolve）。
       refresh() 會串起 detail / identifiers lookup / events / stats 四段 await，
       所以給多一點 tick。 */
    async flush(times = 40) {
      for (let i = 0; i < times; i += 1) await new Promise((r) => setImmediate(r));
    },
  };
}

module.exports = {
  fakeElement, descendants, queryTree, makeFileInput, makeDocument, mount, loadScripts,
};