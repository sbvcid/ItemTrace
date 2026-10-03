/* 用 node 的 vm 在假的 DOM 上跑真正的 ui/item.js。
 *
 * 背景：renderEvents() 曾經把字串當成 el() 的第三引數（children 必須是
 * Array），丟出「(children || []).forEach is not a function」。因為整個
 * start() 被 try/catch 包著，例外被吞成「找不到這件商品」—— 畫面上看不出
 * 真正的原因。
 *
 * 所以這裡跑完整條 render，餵真的資料（含 events、identifiers、有無來源
 * 照片），看有沒有例外、事件有沒有真的渲染出來。
 *
 * 輸出 JSON 給 pytest 讀。執行：node tests/item_dom_harness.js
 */

const { mount } = require("./dom_stubs");

/* 一筆完整的 detail 回應，涵蓋 renderEvents 會走到的分支 */
function detailPayload(options = {}) {
  return {
    item: {
      id: "ITM-0001", name: "ROG STRIX B650E-F", brand: "華碩", model: "B650E-F",
      category: "主機板", quantity: 1, condition: "正常使用", notes: "",
      attributes: {}, status: "active",
      created_at: "2026-10-02T14:00:00", updated_at: "2026-10-02T14:30:00",
    },
    observations: [
      { id: "OBS-20261002-01", item_id: "ITM-0001", kind: "intake",
        note: "出貨前拍攝", captured_at: "2026-10-02T14:30:00",
        created_at: "2026-10-02T14:31:00" },
    ],
    photos: options.withPhotos === false ? [] : [
      { id: "PHOTO1", item_id: "ITM-0001", observation_id: "OBS-20261002-01",
        role: "original", filename: "files/ITM-0001/original/a.jpg",
        orig_name: "IMG_4821.jpg", sha256: "a".repeat(64), bytes: 100,
        width: 4032, height: 3024, captured_at: "2026-10-02T14:30:00",
        angle: "", source: "manual", created_at: "2026-10-02T14:31:00" },
    ],
    identifiers: options.identifiers || [
      { id: "ID1", item_id: "ITM-0001", kind: "serial", value: "BX-807 06_1234",
        normalized: "BX807061234", confidence: 0.9, source: "human",
        source_photo_id: options.withSourcePhoto === false ? null : "PHOTO1",
        created_at: "2026-10-02T14:32:00", updated_at: "2026-10-02T14:32:00" },
    ],
    suggestions: [
      { id: "S1", item_id: "ITM-0001", field: "brand", value: "華碩",
        confidence: 0.9, source: "external", model_name: "demo",
        source_photo_id: "PHOTO1", status: "pending",
        created_at: "2026-10-02T14:33:00", decided_at: null },
    ],
    suggestion_counts: { pending: 1 },
  };
}

/* 一般 event：最常見的一種，prev_value 有值 */
function eventsPayload() {
  return [
    { id: "E1", entity_type: "item", entity_id: "ITM-0001",
      type: "item.created", actor: "user", field: null,
      prev_value: null, next_value: null, payload: {},
      created_at: "2026-10-02T14:30:00" },
    { id: "E2", entity_type: "item", entity_id: "ITM-0001",
      type: "field.changed", actor: "user", field: "brand",
      prev_value: "", next_value: "華碩", payload: {},
      created_at: "2026-10-02T14:40:00" },
    { id: "E3", entity_type: "item", entity_id: "ITM-0001",
      type: "field.changed", actor: "external", field: "quantity",
      prev_value: 1, next_value: 2, payload: {},
      created_at: "2026-10-02T14:50:00" },
    /* actor / entity_type 其中一個是空字串，join 的另一種分支 */
    { id: "E4", entity_type: "item", entity_id: "ITM-0001",
      type: "item.created", actor: "", field: null,
      prev_value: null, next_value: null, payload: {},
      created_at: "2026-10-02T15:00:00" },
  ];
}

/* item.html 裡初始帶 hidden 的元素 */
const INITIALLY_HIDDEN = {
  notfound: true,
  detail: true,
  wall_empty: true,
  id_empty: true,
  obs_empty: true,
  pending_sec: true,
  saved: true,
};

async function scenario(label, options) {
  const calls = [];
  const overrides = {};
  for (const [id, hidden] of Object.entries(INITIALLY_HIDDEN)) {
    const stub = { value: "", textContent: "", dataset: {}, style: {} };
    Object.assign(stub, require("./dom_stubs").fakeElement(id));
    stub.hidden = hidden;
    overrides[id] = stub;
  }

  const view = mount({
    scripts: ["api.js", "item.js"],
    documentOverrides: overrides,
    windowProps: { location: { href: "", pathname: "/items/ITM-0001" } },
    fetchImpl: async (path) => {
      calls.push(path);
      const payload = path.includes("/events")
        ? (options.events || eventsPayload())
        : detailPayload(options);
      return {
        ok: true, status: 200,
        text: async () => (options.failDetail ? "{}" : JSON.stringify(payload)),
      };
    },
  });

  /* start() 是 async IIFE，在第一個 await 就掛起，所以這裡還來得及把
     showError 攔下來 —— 否則真正的原因會被「找不到這件商品」蓋掉。 */
  const shown = [];
  const realShowError = view.sandbox.showError;
  if (typeof realShowError === "function") {
    view.sandbox.showError = (message) => { shown.push(String(message)); return realShowError(message); };
  }

  let error = null;
  try {
    await view.flush();
  } catch (err) {
    error = String(err && err.message ? err.message : err);
  }

  const notFound = view.element("notfound");
  const detail = view.element("detail");
  const eventsBox = view.element("events");

  return {
    label,
    error,
    shownErrors: shown,
    /* 真正的原因不該被「找不到這件商品」蓋掉 */
    notFoundShown: notFound.hidden === false,
    detailShown: detail.hidden === false,
    wallCells: view.element("wall").childNodes.length,
    /* event 每一列都是 class="event" */
    eventRows: eventsBox.countClass("event"),
    called: calls,
  };
}

(async () => {
  const results = [];
  results.push(await scenario("一般情形（有照片、有來源照片、有 events）", {}));
  results.push(await scenario("identifier 沒有來源照片", { withSourcePhoto: false }));
  results.push(await scenario("沒有照片", { withPhotos: false }));
  results.push(await scenario("沒有 identifiers", { identifiers: [] }));
  results.push(await scenario("沒有 events", { events: [] }));
  results.push(await scenario("一筆 events", { events: eventsPayload().slice(0, 1) }));
  results.push(await scenario("detail 抓不到", { failDetail: true }));
  process.stdout.write(JSON.stringify(results, null, 2));
})();