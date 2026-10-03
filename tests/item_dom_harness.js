/* 用 node 的 vm 在假的 DOM 上跑真正的 ui/item.js。
 *
 * 兩個用途：
 *  1. 8A —— renderEvents() 曾經把字串當成 el() 的第三引數（children 必須
 *     是 Array），丟出「(children || []).forEach is not a function」。因為
 *     start() 被 try/catch 包住，例外被吞成「找不到這件商品」，畫面上看不出
 *     真正的原因。
 *  2. 8B —— 真的去點「接受」/「拒絕」，確認按下去會打 API、成功會重載、
 *     失敗（例如 identifier 撞號 409）會顯示錯誤而且不會假裝成功。
 *
 * fetch 可被情境取代，所以能模擬「POST /api/suggestions/x/accept 回 409」。
 * detail 回應也隨情境改變，可以模擬接受後重新載入的結果。
 *
 * 輸出 JSON 給 pytest 讀。執行：node tests/item_dom_harness.js
 */

const { mount } = require("./dom_stubs");

const PHOTO = {
  id: "PHOTO1", item_id: "ITM-0001", observation_id: "OBS-20261002-01",
  role: "original", filename: "files/ITM-0001/original/a.jpg",
  orig_name: "IMG_4821.jpg", sha256: "a".repeat(64), bytes: 100,
  width: 4032, height: 3024, captured_at: "2026-10-02T14:30:00",
  angle: "", source: "manual", created_at: "2026-10-02T14:31:00",
};

function suggestion(id, field, value, extra = {}) {
  return {
    id, item_id: "ITM-0001", field, value,
    confidence: 0.94, source: "external", model_name: "vision-x",
    source_photo_id: "PHOTO1", status: "pending",
    created_at: "2026-10-02T14:33:00", decided_at: null, ...extra,
  };
}

function detailPayload(options = {}) {
  const suggestions = options.suggestions || [suggestion("S1", "brand", "華碩")];
  return {
    item: {
      id: "ITM-0001", name: "ROG STRIX B650E-F",
      brand: options.brand ?? "", model: options.model ?? "",
      category: "", quantity: 1, condition: "", notes: "",
      attributes: {}, status: "active",
      created_at: "2026-10-02T14:00:00", updated_at: "2026-10-02T14:30:00",
    },
    observations: [
      { id: "OBS-20261002-01", item_id: "ITM-0001", kind: "intake",
        note: "出貨前拍攝", captured_at: "2026-10-02T14:30:00",
        created_at: "2026-10-02T14:31:00" },
    ],
    photos: options.withPhotos === false ? [] : [PHOTO],
    identifiers: options.identifiers || [],
    suggestions,
    suggestion_counts: {
      pending: suggestions.filter((s) => s.status === "pending").length,
    },
  };
}

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

function ok(body) {
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
}

function fail(status, detail) {
  return {
    ok: false, status,
    text: async () => JSON.stringify({ detail }),
  };
}

async function mountPage(options = {}) {
  const { fakeElement } = require("./dom_stubs");
  const overrides = {};
  for (const [id, hidden] of Object.entries(INITIALLY_HIDDEN)) {
    const stub = fakeElement(id);
    stub.hidden = hidden;
    overrides[id] = stub;
  }

  const calls = [];
  /* detail 回應會隨「已接受的建議」改變，模擬伺服器真的動了 */
  const state = {
    detail: options.detail || detailPayload(options),
    events: options.events || eventsPayload(),
  };

  const view = mount({
    scripts: ["api.js", "item.js"],
    documentOverrides: overrides,
    windowProps: { location: { href: "", pathname: "/items/ITM-0001" } },
    fetchImpl: async (path, init) => {
      const method = (init && init.method) || "GET";
      calls.push(`${method} ${path}`);

      if (path.includes("/events")) {
        if (options.failEventsAfterSave && state.saved) {
          return fail(503, "歷史服務暫時無法回應");
        }
        return ok(state.events);
      }
      if (path === "/api/stats?limit=1") return ok({ counts: {}, categories: [], recent: [] });
      if (path === "/api/identifiers/lookup") {
        return ok({ value: "", normalized: "", matches: [] });
      }
      /* accept / reject */
      const decision = path.match(/^\/api\/suggestions\/([^/]+)\/(accept|reject)$/);
      if (decision) {
        const [, id, action] = decision;
        if (options.decisionError) {
          return fail(options.decisionError, options.decisionDetail || "已有相同識別碼");
        }
        if (options.onDecide) options.onDecide(state, id, action);
        state.decided = true;
        return ok({ id, status: action === "accept" ? "accepted" : "rejected" });
      }
      /* 欄位 PATCH */
      if (path === "/api/items/ITM-0001" && (init && init.method) === "PATCH") {
        if (options.saveError) {
          return fail(options.saveError, options.saveDetail || "欄位不合法");
        }
        state.saved = true;
        if (options.onSave) options.onSave(state);
        return ok(state.detail.item);
      }
      if (path === "/api/items/ITM-0001") {
        if (options.failDetail) return ok({});
        /* 決定已經成功，但重新載入失敗 —— 8B.1 要驗的就是這個語義 */
        if (state.decided && options.failReloadAfterDecide) {
          return fail(503, "服務暫時無法回應");
        }
        return ok(state.detail);
      }
      return ok({});
    },
  });

  const shown = [];
  const realShowError = view.sandbox.showError;
  if (typeof realShowError === "function") {
    view.sandbox.showError = (m) => { shown.push(String(m)); return realShowError(m); };
  }

  let error = null;
  try {
    await view.flush();
  } catch (err) {
    error = String(err && err.message ? err.message : err);
  }

  const pending = view.element("pending");
  const cards = pending ? pending.childNodes : [];

  return {
    view,
    calls,
    shownErrors: shown,
    error,
    cards,
    buttons: (card, action) =>
      card.querySelectorAll("button").filter((b) => b.dataset.action === action),
    cardText: (card) => card.textContent,
    links: (card) => descendants(cards).length,
    /* 點某一張卡上的按鈕。
       busyDuring 必須在「同步階段跑完、await 之前」量測 —— 等到 await 結束
       之後才看，成功的路徑會因為重新渲染而讀到已經被丟掉的舊節點。 */
    async click(card, action) {
      const button = card.querySelectorAll("button")
        .find((b) => b.dataset.action === action);
      if (!button) return { clicked: false };
      const before = button.disabled;
      const flight = Promise.all(
        (button.listeners.click || []).map((fn) => fn({}))
      );
      const busyDuring = button.disabled;
      await flight;
      await view.flush();
      return { clicked: true, disabledBefore: before, busyDuring };
    },
    identifierRows: () => {
      const tbody = view.query("#identifiers tbody");
      return tbody ? tbody.childNodes.length : 0;
    },
    /* 模擬使用者在表單上打字（FIELDS 的 input listener 會把欄位標成 dirty） */
    async type(fieldId, value) {
      const input = view.element(fieldId);
      input.value = value;
      await Promise.all((input.listeners.input || []).map((fn) => fn({})));
      return input.value;
    },
    field: (fieldId) => view.element(fieldId).value,
  };
}

const { descendants } = require("./dom_stubs");

/* ------------------------------------------------------------------ */

async function scenario(label, options = {}) {
  const page = await mountPage(options);
  const section = page.view.element("pending-sec");

  const base = {
    label,
    error: page.error,
    shownErrors: page.shownErrors,
    notFoundShown: page.view.element("notfound").hidden === false,
    detailShown: page.view.element("detail").hidden === false,
    sectionShown: section.hidden === false,
    sectionCount: page.view.element("pending-count").textContent,
    cardCount: page.cards.length,
    /* 8A 的驗收用 */
    wallCells: page.view.element("wall").childNodes.length,
    eventRows: page.view.element("events").countClass("event"),
    cards: page.cards.map((card) => ({
      id: card.dataset.suggestion || null,
      text: page.cardText(card),
      actions: card.querySelectorAll("button").map((b) => b.dataset.action),
      sourceHref: (card.querySelectorAll("a")[0] || {}).getAttribute
        ? (card.querySelectorAll("a")[0] || {}).getAttribute("href") || null
        : null,
      errorText: card.querySelector(".sugg-error")
        ? card.querySelector(".sugg-error").textContent : null,
      errorHidden: card.querySelector(".sugg-error")
        ? card.querySelector(".sugg-error").hidden : null,
      disabled: card.querySelectorAll("button").map((b) => b.disabled),
    })),
    calls: page.calls,
  };

  if (options.click) {
    const index = options.click.card ?? 0;
    const card = page.cards[index];
    if (!card) return { ...base, clicked: { clicked: false } };
    /* 先模擬使用者正在打字，再點接受 —— 未存檔的內容不能被重載蓋掉 */
    if (options.typedBeforeClick) {
      await page.type(options.typedBeforeClick.field, options.typedBeforeClick.value);
    }
    const result = await page.click(card, options.click.action);
    const after = page.view.element("pending");
    const afterCards = after.childNodes;
    const target = options.click.errorOn409
      ? afterCards.find((c) => c.dataset.suggestion === card.dataset.suggestion)
      : null;
    return {
      ...base,
      clicked: result,
      afterCardCount: afterCards.length,
      afterActions: target
        ? target.querySelectorAll("button").map((b) => b.dataset.action)
        : [],
      afterDisabled: target
        ? target.querySelectorAll("button").map((b) => b.disabled)
        : [],
      afterErrorText: target ? (target.querySelector(".sugg-error") || {}).textContent : "",
      afterErrorHidden: target && target.querySelector(".sugg-error")
        ? target.querySelector(".sugg-error").hidden : null,
      afterBrand: page.view.element("f-brand").value,
      afterNotes: page.field("f-notes"),
      afterIdentifierRows: page.identifierRows(),
      afterSectionShown: page.view.element("pending-sec").hidden === false,
    };
  }
  if (options.submitForm) {
    const form = page.view.element("form");
    const input = page.view.element("f-brand");
    input.value = "華碩";
    await Promise.all((input.listeners.input || []).map((fn) => fn({})));
    await Promise.all((form.listeners.submit || []).map((fn) => fn({ preventDefault() {} })));
    await page.view.flush();
    return {
      ...base,
      savedText: page.view.element("saved").textContent,
      savedHidden: page.view.element("saved").hidden,
      errorBoxText: (page.view.element("error") || {}).textContent || "",
      errorBoxChildren: page.view.element("error").childNodes.map((c) => c.textContent),
      saveButtonDisabled: page.view.element("save").disabled,
      afterBrand: page.view.element("f-brand").value,
    };
  }
  return base;
}

(async () => {
  const results = [];

  /* 8A 的渲染情境 */
  results.push(await scenario("一般情形", {}));
  results.push(await scenario("identifier 沒有來源照片", {
    identifiers: [{ id: "ID1", item_id: "ITM-0001", kind: "serial",
      value: "BX-807 06_1234", normalized: "BX807061234", confidence: 0.9,
      source: "human", source_photo_id: null,
      created_at: "2026-10-02T14:32:00", updated_at: "2026-10-02T14:32:00" }],
  }));
  results.push(await scenario("沒有照片", { withPhotos: false }));
  results.push(await scenario("沒有 identifiers", { identifiers: [] }));
  results.push(await scenario("沒有 events", { events: [] }));
  results.push(await scenario("一筆 events", { events: eventsPayload().slice(0, 1) }));
  results.push(await scenario("detail 抓不到", { failDetail: true }));

  /* 8B 的建議操作情境 */
  results.push(await scenario("建議顯示資料", {
    suggestions: [
      suggestion("S1", "brand", "華碩"),
      suggestion("S2", "identifier:serial", "XXXX-123456"),
    ],
  }));
  results.push(await scenario("建議沒有來源照片", {
    suggestions: [
      suggestion("S1", "brand", "華碩", { source_photo_id: null }),
      suggestion("S2", "brand", "孤兒來源", { source_photo_id: "PHOTO-MISSING" }),
    ],
  }));
  results.push(await scenario("沒有 pending 建議", {
    suggestions: [suggestion("S1", "brand", "華碩", { status: "accepted" })],
  }));
  results.push(await scenario("接受一般欄位", {
    onDecide: (state, id, action) => {
      state.detail.item.brand = "華碩";
      state.detail.suggestions[0].status = "accepted";
      state.detail.suggestion_counts = { accepted: 1 };
    },
    click: { card: 0, action: "accept" },
  }));
  results.push(await scenario("拒絕一般欄位", {
    onDecide: (state) => {
      state.detail.suggestions[0].status = "rejected";
      state.detail.suggestion_counts = { rejected: 1 };
    },
    click: { card: 0, action: "reject" },
  }));
  results.push(await scenario("接受 identifier", {
    suggestions: [suggestion("S1", "identifier:serial", "XXXX-123456")],
    onDecide: (state) => {
      state.detail.identifiers = [
        { id: "ID9", item_id: "ITM-0001", kind: "serial", value: "XXXX-123456",
          normalized: "XXXX123456", confidence: 0.62, source: "accepted_suggestion",
          source_photo_id: "PHOTO1", created_at: "2026-10-03T10:00:00",
          updated_at: "2026-10-03T10:00:00" },
      ];
      state.detail.suggestions[0].status = "accepted";
    },
    click: { card: 0, action: "accept" },
  }));
  results.push(await scenario("accept 回 409", {
    suggestions: [suggestion("S1", "identifier:serial", "ABC123")],
    decisionError: 409,
    decisionDetail: "其他商品已有正規化後相同的識別碼",
    click: { card: 0, action: "accept", errorOn409: true },
  }));
  results.push(await scenario("accept 回 500", {
    decisionError: 500,
    decisionDetail: "boom",
    click: { card: 0, action: "accept", errorOn409: true },
  }));
  results.push(await scenario("先打字再接受", {
    typedBeforeClick: { field: "f-notes", value: "我還沒存檔的備註" },
    onDecide: (state) => {
      state.detail.item.brand = "華碩";
      state.detail.suggestions[0].status = "accepted";
    },
    click: { card: 0, action: "accept" },
  }));

  /* 8B.1：POST 成功，但重載失敗 */
  results.push(await scenario("接受成功但重載失敗", {
    failReloadAfterDecide: true,
    onDecide: (state) => { state.detail.item.brand = "華碩"; },
    click: { card: 0, action: "accept", errorOn409: true },
  }));
  results.push(await scenario("拒絕成功但重載失敗", {
    failReloadAfterDecide: true,
    click: { card: 0, action: "reject", errorOn409: true },
  }));
  /* 對照組：PATCH 成功但歷史載入失敗 */
  results.push(await scenario("欄位儲存成功但歷史載入失敗", {
    failEventsAfterSave: true,
    submitForm: true,
  }));

  process.stdout.write(JSON.stringify(results, null, 2));
})();