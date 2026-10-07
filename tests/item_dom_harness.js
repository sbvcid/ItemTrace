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

function eventsPayload(options = {}) {
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
    ...(options.extraEvents || []),
  ];
}

/* Phase 9：不可復原的事件 —— 沒有 field、prev_value 是 null、或不是 field.changed。
   這些不該出現「復原」按鈕。 */
function nonRevertibleEvents() {
  return [
    { id: "N1", entity_type: "item", entity_id: "ITM-0001",
      type: "field.changed", actor: "user", field: null,
      prev_value: "x", next_value: "y", payload: {},
      created_at: "2026-10-02T16:00:00" },
    { id: "N2", entity_type: "item", entity_id: "ITM-0001",
      type: "field.changed", actor: "user", field: "brand",
      prev_value: null, next_value: "y", payload: {},
      created_at: "2026-10-02T16:01:00" },
    { id: "N3", entity_type: "item", entity_id: "ITM-0001",
      type: "item.created", actor: "user", field: null,
      prev_value: null, next_value: null, payload: {},
      created_at: "2026-10-02T16:02:00" },
    { id: "N4", entity_type: "suggestion", entity_id: "S1",
      type: "suggestion.accepted", actor: "user", field: "brand",
      prev_value: "ASUS", next_value: "ASUS", payload: {},
      created_at: "2026-10-02T16:03:00" },
    { id: "N5", entity_type: "identifier", entity_id: "ID1",
      type: "identifier.deleted", actor: "user", field: null,
      prev_value: null, next_value: null, payload: {},
      created_at: "2026-10-02T16:04:00" },
  ];
}

/* Phase 9.1：entity_type / field 的完整矩陣。
   UI 的 canRevert() 比 backend 的 revert_event() 嚴格：後端還會檢查
   entity_type 與該 entity 的可改欄位。這裡把兩邊的邊界案例都列出來。 */
function revertMatrix() {
  const at = (id, entity_type, field, extra) => ({
    id, entity_type, entity_id: "X1", type: "field.changed",
    actor: "user", field, prev_value: "A", next_value: "B",
    payload: {}, created_at: "2026-10-02T17:00:00", ...extra,
  });
  return [
    /* item：後端允許的欄位 → 有按鈕 */
    at("M01", "item", "brand"),
    at("M02", "item", "quantity"),
    at("M03", "item", "attributes"),
    at("M04", "item", "status"),
    /* item：後端不允許的欄位 → 無按鈕 */
    at("M05", "item", "not_a_real_field"),
    at("M06", "item", "created_at"),
    at("M07", "item", "id"),
    /* identifier：後端允許 → 有按鈕 */
    at("M10", "identifier", "value"),
    at("M11", "identifier", "kind"),
    at("M12", "identifier", "confidence"),
    /* identifier：normalized 有 field.changed 但後端不允許復原 */
    at("M13", "identifier", "normalized"),
    at("M14", "identifier", "not_a_field"),
    /* observation / photo / suggestion：UI 刻意不支援 */
    at("M20", "observation", "note"),
    at("M21", "observation", "captured_at"),
    at("M22", "photo", "angle"),
    at("M23", "photo", "role"),
    at("M24", "suggestion", "value"),
    at("M25", "suggestion", "confidence"),
    /* 未知 entity_type */
    at("M30", "invoice", "total"),
    at("M31", "unknown_thing", "whatever"),
    /* field / prev_value 為 null，以及不是 field.changed */
    at("M40", "item", null),
    at("M41", "item", "brand", { prev_value: null }),
    at("M42", "item", "brand", { type: "item.created" }),
  ];
}

/* item.html 裡初始帶 hidden 的元素。print_dialog 是列印對話框，
   初始必須是隱藏的 —— 沒有對應的 .hidden class，只看 hidden 屬性。 */
const INITIALLY_HIDDEN = {
  notfound: true,
  detail: true,
  wall_empty: true,
  id_empty: true,
  obs_empty: true,
  pending_sec: true,
  saved: true,
  print_dialog: true,
};

/* 商品頁的列印測試資料。列印流程需要 templates、printers、settings。 */
const PRINT_TEMPLATES = [
  { id: "TPL-0002", name: "Label 100x150", html: "<html></html>",
    width: 100, height: 150, unit: "mm",
    created_at: "2024-01-01T00:00:00", updated_at: "2024-02-01T00:00:00" },
  { id: "TPL-0003", name: "Small 60x40", html: "<html></html>",
    width: 60, height: 40, unit: "mm",
    created_at: "2024-01-02T00:00:00", updated_at: "2024-02-02T00:00:00" },
];

const PRINT_PRINTERS = [
  { name: "Microsoft Print to PDF", is_default: false },
  { name: "Xprinter XP-470E", is_default: true },
];

/* print-preview 回傳的 html：每個範本一份，用來驗證「切換範本會換預覽」。 */
function printPreviewHtml(templateId, itemId) {
  return `<html><body><h1>PRINT:${templateId}</h1><p>item:${itemId}</p></body></html>`;
}

function printPreviewPayload(templateId, itemId) {
  const template = PRINT_TEMPLATES.find((t) => t.id === templateId) || {};
  return {
    printer: "",
    item_id: itemId,
    item_name: "ROG STRIX B650E-F",
    template_id: templateId,
    width_mm: template.width || 100,
    height_mm: template.height || 150,
    pixel_width: 0, pixel_height: 0, dpi: 300,
    pdf_width_mm: template.width || 100,
    pdf_height_mm: template.height || 150,
    html: printPreviewHtml(templateId, itemId),
  };
}

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
  /* 列印預設值：預設範本 TPL-0002、預設印表機 Xprinter。 */
  const settings = options.settings || {
    printer: "Xprinter XP-470E",
    template_id: "TPL-0002",
    exists: true,
    error: null,
  };
  /* 讀不到 /api/printers 時要保留真正的錯誤原因，而不是被印表機清單
     為空那個訊息蓋掉。 */
  const printerListError = options.printersError
    ? `讀取印表機清單失敗: ${options.printersError}`
    : null;
  /* 記錄實際呼叫過 print-preview 的範本順序，用來驗證切換範本會重新載入。 */
  const printState = { previews: [] };

  const view = mount({
    /* print_dialog.js 必須排在 item.js 之前：item.js 頂層就呼叫
     printBind()，沒有它就直接 ReferenceError（整頁的腳本都不會跑）。 */
    scripts: ["api.js", "print_dialog.js", "item.js"],
    documentOverrides: overrides,
    windowProps: { location: { href: "", pathname: "/items/ITM-0001" } },
    fetchImpl: async (path, init) => {
      const method = (init && init.method) || "GET";
      calls.push(`${method} ${path}`);

      /* Phase 9：復原單一事件。
         必須排在下面 GET /events 的分支之前 ——
         "/api/events/E2/revert" 也包含 "/events"。 */
      const revert = path.match(/^\/api\/events\/([^/]+)\/revert$/);
      if (revert) {
        const [, id] = revert;
        if (options.revertError) {
          return fail(options.revertError, options.revertDetail || "只有 field.changed 事件可復原");
        }
        state.reverted = id;
        if (options.onRevert) options.onRevert(state, id);
        return ok(state.detail.item);
      }
      if (path.includes("/events")) {
        if (options.failEventsAfterSave && state.saved) {
          return fail(503, "歷史服務暫時無法回應");
        }
        /* 決定已經成功，但 events 掛掉 —— refresh 中途失敗的那種 */
        if (state.decided && options.failEventsAfterDecide) {
          return fail(503, "歷史服務暫時無法回應");
        }
        /* 復原已成功，但 events 掛掉 —— Phase 9 的對應情境 */
        if (state.reverted && options.failEventsAfterRevert) {
          return fail(503, "歷史服務暫時無法回應");
        }
        return ok(state.events);
      }
      /* ---- 列印（ui/print_dialog.js 走同一組 api()） ----
         這些分支必須排在下面的 catch-all `return ok({})` 之前，
         否則預設回應會讓對話框「看起來成功但什麼都沒載入」。 */
      if (path === "/api/settings/printing") {
        if ((init && init.method) === "POST") return ok(settings);
        return ok(settings);
      }
      if (path === "/api/templates?limit=200") return ok(PRINT_TEMPLATES);
      if (path === "/api/printers") {
        if (printerListError) return fail(400, options.printersError);
        return ok(options.printers !== undefined ? options.printers : PRINT_PRINTERS);
      }
      if (path === "/api/items?limit=200") {
        return ok([{ id: "ITM-0001", name: "ROG STRIX B650E-F" }]);
      }
      const printPreview = path.match(
        /^\/api\/templates\/([^/]+)\/print-preview$/);
      if (printPreview && (init && init.method) === "POST") {
        if (options.printPreviewError) {
          return fail(400, options.printPreviewError);
        }
        const body = JSON.parse(init.body);
        const preview = printPreviewPayload(printPreview[1], body.item_id);
        printState.previews.push(preview.template_id);
        return ok(preview);
      }
      const doPrint = path.match(/^\/api\/templates\/([^/]+)\/print$/);
      if (doPrint && (init && init.method) === "POST") {
        if (options.printError) return fail(400, options.printError);
        const body = JSON.parse(init.body);
        const payload = printPreviewPayload(doPrint[1], body.item_id);
        return ok({
          ...payload,
          printer: body.printer || "Xprinter XP-470E",
          pixel_width: 1182, pixel_height: 1772,
        });
      }

      if (path === "/api/stats?limit=1") return ok({ counts: {}, categories: [], recent: [] });
      if (path.includes("/api/identifiers/lookup")) {
        return ok({ value: "", normalized: "", matches: options.collisionMatches || [] });
      }
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
        /* 復原已經成功，但 detail 載不回來 —— Phase 9 的對應情境 */
        if (state.reverted && options.failReloadAfterRevert) {
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
    /* ---- 列印相關的觀察點 ---- */
    print: {
      previews: printState.previews,
      dialogHidden: () => view.element("print-dialog").hidden === true,
      dialogVisible: () => view.element("print-dialog").hidden === false,
      templateOptions: () =>
        view.element("print-template").childNodes.map((o) => ({
          value: o.value, text: o.textContent,
        })),
      /* 假 DOM 不會從 selectedIndex 同步 select.value，所以要自己換算 ——
         否則「選了哪一個」永遠讀成空字串，會把真正的問題遮掉。 */
      selectedTemplate: () => {
        const select = view.element("print-template");
        const chosen = select.childNodes[select.selectedIndex];
        return chosen ? chosen.value : null;
      },
      printerOptions: () =>
        view.element("print-printer").childNodes.map((o) => o.value),
      selectedPrinter: () => {
        const select = view.element("print-printer");
        const chosen = select.childNodes[select.selectedIndex];
        return chosen ? chosen.value : null;
      },
      sizeText: () => view.element("print-size").textContent,
      errorText: () => view.element("print-error").textContent,
      confirmDisabled: () => view.element("print-confirm").disabled === true,
      confirmLabel: () => view.element("print-confirm").textContent,
      previewSrcdoc: () => {
        const frames = view.element("print-preview").childNodes
          .filter((n) => String(n.tagName || "").toUpperCase() === "IFRAME");
        return frames.length ? frames[0].getAttribute("srcdoc") : null;
      },
      /* 商品頁不該有商品下拉：商品固定是本頁這一件。 */
      hasItemSelect: () => Boolean(view.element("print-item")),
      open: async () => {
        const button = view.element("print-label");
        await Promise.all(
          (button.listeners.click || []).map((fn) => fn({}))
        );
        await view.flush();
      },
      switchTemplate: async (value) => {
        const select = view.element("print-template");
        select.value = value;
        await Promise.all(
          (select.listeners.change || []).map((fn) => fn({}))
        );
        await view.flush();
      },
      confirm: async () => {
        const button = view.element("print-confirm");
        await Promise.all(
          (button.listeners.click || []).map((fn) => fn({}))
        );
        await view.flush();
      },
    },
    /* 歷史每一列 */
    rows: view.element("events").childNodes,
    buttons: (card, action) =>
      card.querySelectorAll("button").filter((b) => b.dataset.action === action),
    cardText: (card) => card.textContent,
    /* 點某一列上的復原鈕 */
    async clickRevert(eventId) {
      const row = view.element("events").childNodes
        .find((r) => r.dataset.event === eventId);
      if (!row) return { clicked: false };
      const button = row.querySelectorAll("button")
        .find((b) => b.dataset.action === "revert");
      if (!button) return { clicked: false, noButton: true };
      const flight = Promise.all((button.listeners.click || []).map((fn) => fn({})));
      const busyDuring = button.disabled;
      await flight;
      await view.flush();
      return { clicked: true, busyDuring };
    },
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
    eventRowCount: page.view.element("events").countClass("event"),
    /* Phase 10 §6：來源照片縮圖與撞號連結 */
    thumbs: page.view
      .all((n) => n.dataset && n.dataset.role === "source-thumb")
      .map((n) => ({
        src: n.querySelector("img")
          ? n.querySelector("img").getAttribute("src") : null,
        title: n.getAttribute("title") || null,
      })),
    collisionLinks: page.view
      .all((n) => n.dataset && n.dataset.collisionLink)
      .map((n) => ({
        item: n.dataset.collisionLink,
        href: n.getAttribute("href"),
      })),
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
    /* 歷史每一列的可復原性與文案 */
    eventRows: (page.view.element("events").childNodes || []).map((row) => ({
      id: row.dataset.event || null,
      text: row.textContent,
      actions: row.querySelectorAll("button").map((b) => b.dataset.action),
      disabled: row.querySelectorAll("button").map((b) => b.disabled),
      errorText: row.querySelector(".event-error")
        ? row.querySelector(".event-error").textContent : null,
      errorHidden: row.querySelector(".event-error")
        ? row.querySelector(".event-error").hidden : null,
    })),
  };

  /* 列印情境：開啟對話框 →（選範本）→（送出），
     回報對話框實際顯示了什麼。放在最前面，因為它是整個列印路徑的驗收。 */
  if (options.print) {
    await page.print.open();
    const opened = {
      dialogVisible: page.print.dialogVisible(),
      templateOptions: page.print.templateOptions(),
      selectedTemplate: page.print.selectedTemplate(),
      printerOptions: page.print.printerOptions(),
      selectedPrinter: page.print.selectedPrinter(),
      sizeText: page.print.sizeText(),
      errorText: page.print.errorText(),
      confirmDisabled: page.print.confirmDisabled(),
      previewSrcdoc: page.print.previewSrcdoc(),
      hasItemSelect: page.print.hasItemSelect(),
    };
    if (options.print.switchTemplate) {
      await page.print.switchTemplate(options.print.switchTemplate);
    }
    if (options.print.confirm) {
      await page.print.confirm();
    }
    return {
      ...base,
      printOpened: opened,
      printAfter: {
        templateOptions: page.print.templateOptions(),
        selectedTemplate: page.print.selectedTemplate(),
        selectedPrinter: page.print.selectedPrinter(),
        sizeText: page.print.sizeText(),
        errorText: page.print.errorText(),
        confirmDisabled: page.print.confirmDisabled(),
        confirmLabel: page.print.confirmLabel(),
        previewSrcdoc: page.print.previewSrcdoc(),
        previewCalls: page.print.previews,
        dialogVisible: page.print.dialogVisible(),
      },
      printCalls: page.calls.filter((c) => /print|settings/.test(c)),
    };
  }

  if (options.revertEvent) {
    const result = await page.clickRevert(options.revertEvent);
    const after = page.view.element("events").childNodes;
    const target = after.find((r) => r.dataset.event === options.revertEvent);
    return {
      ...base,
      reverted: result,
      afterEventIds: after.map((r) => r.dataset.event),
      afterRowActions: target
        ? target.querySelectorAll("button").map((b) => b.dataset.action) : [],
      afterRowDisabled: target
        ? target.querySelectorAll("button").map((b) => b.disabled) : [],
      afterRowError: target && target.querySelector(".event-error")
        ? target.querySelector(".event-error").textContent : "",
      afterPageError: page.view.element("error").childNodes.map((c) => c.textContent),
      afterBrand: page.view.element("f-brand").value,
      afterEventCount: page.view.element("event-count").textContent,
    };
  }

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
      /* 頁面層級的提示區（#error）。reload 失敗的訊息必須落在這裡 ——
         放在卡片上沒用，refresh() 可能已經把那張卡換掉了。 */
      afterPageError: page.view.element("error").childNodes.map((c) => c.textContent),
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

  /* Phase 10 §6：識別碼旁要有來源照片縮圖，撞號要有既有 item 的連結 */
  results.push(await scenario("識別碼縮圖（沒有建議）", {
    suggestions: [],
    identifiers: [
      { id: "ID1", item_id: "ITM-0001", kind: "serial", value: "BX-807 06_1234",
        normalized: "BX807061234", confidence: 0.9, source: "human",
        source_photo_id: "PHOTO1",
        created_at: "2026-10-02T14:32:00", updated_at: "2026-10-02T14:32:00" },
      { id: "ID2", item_id: "ITM-0001", kind: "imei", value: "990000862471854",
        normalized: "990000862471854", confidence: null, source: "human",
        source_photo_id: null,
        created_at: "2026-10-02T14:33:00", updated_at: "2026-10-02T14:33:00" },
    ],
  }));
  results.push(await scenario("識別碼縮圖與撞號連結", {
    identifiers: [
      { id: "ID1", item_id: "ITM-0001", kind: "serial", value: "BX-807 06_1234",
        normalized: "BX807061234", confidence: 0.9, source: "human",
        source_photo_id: "PHOTO1",
        created_at: "2026-10-02T14:32:00", updated_at: "2026-10-02T14:32:00" },
      { id: "ID2", item_id: "ITM-0001", kind: "imei", value: "990000862471854",
        normalized: "990000862471854", confidence: null, source: "human",
        source_photo_id: null,
        created_at: "2026-10-02T14:33:00", updated_at: "2026-10-02T14:33:00" },
    ],
    collisionMatches: [
      /* 另一件商品有正規化後相同的識別碼 */
      { id: "ID9", item_id: "ITM-0007", kind: "serial", value: "BX-807 06_1234",
        normalized: "BX807061234", confidence: 0.5, source: "human",
        source_photo_id: null,
        created_at: "2026-09-01T10:00:00", updated_at: "2026-09-01T10:00:00" },
    ],
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
  /* 8B.1 的第二種：detail 成功（卡片已被換掉）、events 才失敗 */
  results.push(await scenario("接受成功但歷史載入失敗", {
    failEventsAfterDecide: true,
    onDecide: (state) => {
      state.detail.item.brand = "華碩";
      state.detail.suggestions[0].status = "accepted";
    },
    click: { card: 0, action: "accept", errorOn409: true },
  }));
  results.push(await scenario("拒絕成功但歷史載入失敗", {
    failEventsAfterDecide: true,
    onDecide: (state) => { state.detail.suggestions[0].status = "rejected"; },
    click: { card: 0, action: "reject", errorOn409: true },
  }));
  /* 對照組：PATCH 成功但歷史載入失敗 */
  results.push(await scenario("欄位儲存成功但歷史載入失敗", {
    failEventsAfterSave: true,
    submitForm: true,
  }));

  /* Phase 9 的復原情境 */
  results.push(await scenario("復原按鈕只出現在可復原事件", {
    events: eventsPayload({ extraEvents: nonRevertibleEvents() }),
  }));
  results.push(await scenario("entity/field 矩陣", {
    events: eventsPayload({ extraEvents: revertMatrix() }),
  }));
  results.push(await scenario("復原成功", {
    events: eventsPayload(),
    brand: "華碩",
    revertEvent: "E2",
    onRevert: (state) => {
      state.detail.item.brand = "";
      /* 後端會另記一筆 field.changed，原事件不動 → A → B → A 完整鏈 */
      state.events = [
        { id: "E5", entity_type: "item", entity_id: "ITM-0001",
          type: "field.changed", actor: "user", field: "brand",
          prev_value: "華碩", next_value: "", payload: {},
          created_at: "2026-10-02T17:00:00" },
        ...state.events,
      ];
    },
  }));
  results.push(await scenario("復原失敗 400", {
    events: eventsPayload(),
    brand: "華碩",
    revertError: 400,
    revertDetail: "只有 field.changed 事件可復原（需同時有 field 與 prev_value）",
    revertEvent: "E2",
  }));
  results.push(await scenario("復原失敗 409", {
    events: eventsPayload(),
    brand: "華碩",
    revertError: 409,
    revertDetail: "其他商品已有正規化後相同的識別碼",
    revertEvent: "E3",
  }));
  results.push(await scenario("復原失敗 500", {
    events: eventsPayload(),
    brand: "華碩",
    revertError: 500,
    revertDetail: "boom",
    revertEvent: "E2",
  }));
  results.push(await scenario("復原成功但重載失敗", {
    events: eventsPayload(),
    brand: "華碩",
    failReloadAfterRevert: true,
    revertEvent: "E2",
    onRevert: (state) => { state.detail.item.brand = ""; },
  }));
  results.push(await scenario("復原成功但歷史載入失敗", {
    events: eventsPayload(),
    brand: "華碩",
    failEventsAfterRevert: true,
    revertEvent: "E2",
    onRevert: (state) => { state.detail.item.brand = ""; },
  }));

  /* ------------------------------------------------------------------
   * 商品頁列印：只有「挑範本 → 看預覽 → 列印」。
   * ------------------------------------------------------------------ */

  // 預設值套用：範本與印表機都來自設定
  results.push(await scenario("列印對話框套用預設值", {
    print: {},
  }));

  // 沒有設定檔時退回 Windows 預設印表機與第一個範本
  results.push(await scenario("列印對話框沒有設定值", {
    settings: { printer: null, template_id: null, exists: false, error: null },
    print: {},
  }));

  // 切換範本 → 重新取得預覽，且不修改範本本身
  results.push(await scenario("切換範本會更新預覽", {
    print: { switchTemplate: "TPL-0003" },
  }));

  // 送出列印：1 份、用選定的印表機
  results.push(await scenario("商品頁送出一份列印", {
    print: { confirm: true },
  }));

  // 沒有印表機要說清楚
  results.push(await scenario("列印時找不到印表機", {
    printers: [],
    print: {},
  }));

  results.push(await scenario("讀不到印表機清單", {
    printersError: "缺少 pywin32",
    print: {},
  }));

  results.push(await scenario("列印預覽載入失敗", {
    printPreviewError: "Template 渲染失敗",
    print: {},
  }));

  results.push(await scenario("列印送出失敗", {
    printError: "找不到印表機：Nope",
    print: { confirm: true },
  }));

  process.stdout.write(JSON.stringify(results, null, 2));
})();