/* 用 node 的 vm 在假的 DOM 上跑真正的 ui/printing_settings.js。
 *
 * 驗的是「設定 → 列印」這一頁的實際行為：
 *   - 預設印表機／預設範本能不能讀寫（/api/settings/printing）
 *   - 範本管理：列表、新增、編輯、刪除
 *   - 列印對話框是否套用設定值
 *
 * 為什麼要有這支：這一頁同時用到列印設定與範本 CRUD，字串比對測不出
 * 「按儲存之後下拉有沒有真的改變」或「刪掉的那筆有沒有從列表消失」。
 *
 * 輸出 JSON 給 pytest 讀。執行：node tests/printing_dom_harness.js
 */

const { mount, makeFileInput, fakeElement } = require("./dom_stubs");

const CARD_HTML = `<!doctype html><html><head><style>
.label{width:100mm;height:150mm}
</style></head><body><div class="label"><img data-bind-src="item.primary_photo" alt="">
<h1 data-bind="item.name"></h1></div></body></html>`;

const SEEDED = [
  { id: "TPL-0002", name: "Label 100x150", html: CARD_HTML,
    width: 100, height: 150, unit: "mm",
    created_at: "2024-01-01T00:00:00", updated_at: "2024-02-01T00:00:00" },
  { id: "TPL-0003", name: "Small 60x40", html: CARD_HTML,
    width: 60, height: 40, unit: "mm",
    created_at: "2024-01-02T00:00:00", updated_at: "2024-02-02T00:00:00" },
];

const PRINT_PRINTERS = [
  { name: "Microsoft Print to PDF", is_default: false },
  { name: "Xprinter XP-470E", is_default: true },
];

const ITEMS = [{ id: "ITM-0001", name: "AMD Ryzen 7 9700X" }];

function printPreviewPayload(templateId) {
  const template = SEEDED.find((t) => t.id === templateId) || {};
  return {
    printer: "",
    item_id: "ITM-0001",
    item_name: "AMD Ryzen 7 9700X",
    template_id: templateId,
    width_mm: template.width || 100,
    height_mm: template.height || 150,
    pixel_width: 0, pixel_height: 0, dpi: 300,
    pdf_width_mm: template.width || 100,
    pdf_height_mm: template.height || 150,
    html: `<html><body><h1>PRINT:${templateId}</h1></body></html>`,
  };
}

function ok(body) {
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
}
function fail(status, detail) {
  return { ok: false, status, text: async () => JSON.stringify({ detail }) };
}

function isTag(node, tag) {
  return String((node && node.tagName) || "").toUpperCase() === tag.toUpperCase();
}

async function mountPage(options = {}) {
  const calls = [];
  const alerts = [];
  const unmapped = [];
  /* templates 在 harness 自己的陣列裡：GET 回列表、POST/PUT/DELETE 都
     真的改它，「上傳完列表要重新載入才有新卡片」才測得到。 */
  const templates = (options.initialTemplates || SEEDED).map((t) => ({ ...t }));
  /* 設定檔的內容跟著 store 變，模擬 server 端真的存下來了。 */
  const store = {
    printer: null,
    template_id: null,
    ...(options.settings || {}),
  };

  /* requests 同時記「METHOD path」字串（方便逐行比對）與結構化版本
     （path / method / body），後者給斷言 request payload 用。 */
  const requests = [];
  const fetchImpl = async (path, init) => {
    const method = (init && init.method) || "GET";
    const body = init && init.body ? JSON.parse(init.body) : null;
    calls.push(`${method} ${path}`);
    requests.push({ method, path, body });

    if (path === "/api/settings/printing") {
      if (method === "POST") {
        if (options.saveError) return fail(400, options.saveError);
        store.printer = body.printer;
        store.template_id = body.template_id;
      }
      return ok({
        printer: store.printer, template_id: store.template_id,
        exists: true, error: null,
      });
    }
    if (path === "/api/printers") {
      if (options.printersError) return fail(400, options.printersError);
      return ok(options.printers !== undefined ? options.printers : PRINT_PRINTERS);
    }
    if (path === "/api/items?limit=200") return ok(ITEMS);
    if (path.startsWith("/api/templates?") && method === "GET") {
      return ok(templates.map((t) => ({ ...t })));
    }
    if (path === "/api/templates" && method === "POST") {
      if (options.createError) return fail(400, options.createError);
      const created = { id: `TPL-${9000 + templates.length}`, ...body };
      templates.push(created);
      return ok({ ...created });
    }

    const printPreview = path.match(/^\/api\/templates\/([^/]+)\/print-preview$/);
    if (printPreview && method === "POST") {
      if (options.printPreviewError) return fail(400, options.printPreviewError);
      return ok(printPreviewPayload(printPreview[1]));
    }
    const doPrint = path.match(/^\/api\/templates\/([^/]+)\/print$/);
    if (doPrint && method === "POST") {
      if (options.printError) return fail(400, options.printError);
      return ok({
        ...printPreviewPayload(doPrint[1]),
        printer: body.printer || "Xprinter XP-470E",
        pixel_width: 1182, pixel_height: 1772,
      });
    }

    const single = path.match(/^\/api\/templates\/([^/]+)$/);
    if (single) {
      const id = single[1];
      const index = templates.findIndex((t) => t.id === id);
      if (index === -1) return fail(404, "template 不存在");
      if (method === "PUT") {
        if (options.updateError) return fail(400, options.updateError);
        templates[index] = { ...templates[index], ...body };
        return ok({ ...templates[index] });
      }
      if (method === "DELETE") {
        templates.splice(index, 1);
        return ok({});
      }
    }
    /* 範本預覽（管理用） */
    const preview = path.match(/^\/api\/templates\/([^/]+)\/preview$/);
    if (preview && method === "POST") {
      if (options.previewError) return fail(400, options.previewError);
      return ok({
        html: `<html><body><h1>PREVIEW:${preview[1]}</h1></body></html>`,
        item_id: body.item_id, item_name: "AMD Ryzen 7 9700X",
      });
    }

    unmapped.push(`${method} ${path}`);
    return ok({});
  };

  /* printing_settings.html 初始帶 hidden 的元素。 */
  const seeded = {};
  for (const id of ["template-editor", "print-dialog"]) {
    const node = fakeElement(id);
    node.hidden = true;
    seeded[id] = node;
  }

  const view = mount({
    /* print_dialog.js 必須在前面：printing_settings.js 頂層就呼叫
       printBind()，沒有它會 ReferenceError，整頁腳本都不跑。 */
    scripts: ["print_dialog.js", "printing_settings.js"],
    windowProps: {
      location: { href: "", pathname: "/settings/printing", origin: "http://127.0.0.1" },
      confirm: () => options.confirmAnswer !== false,
      alert: (message) => { alerts.push(String(message)); },
    },
    documentOverrides: seeded,
    fetchImpl,
  });

  const el = (id) => view.element(id);
  const selectedValue = (id) => {
    const select = el(id);
    const chosen = select.childNodes[select.selectedIndex];
    return chosen ? chosen.value : null;
  };

  return {
    view, calls, requests, alerts, unmapped, el, store, templates, selectedValue,
    async flush() { await view.flush(); },
    /* 送出 body 的那次 request（POST /api/settings/printing） */
    posted: (method, path) =>
      requests.find((r) => r.method === method && r.path === path),
    put: (path) =>
      requests.find((r) => r.method === "PUT" && r.path === path),
    async click(node) {
      if (!node) throw new Error("找不到按鈕");
      await node.fire("click", {});
      await view.flush();
    },
    rowButtons(rowIndex, label) {
      const row = el("template-rows").childNodes[rowIndex];
      if (!row) return null;
      return row.querySelectorAll("button").find((b) => b.textContent === label);
    },
    tableRowTexts: () =>
      el("template-rows").childNodes.map((row) =>
        row.childNodes.map((cell) => cell.textContent)
      ),
    async submitTemplateForm(name, html, width, height) {
      el("template-name").value = name;
      el("template-html").value = html;
      el("template-width").value = width || "";
      el("template-height").value = height || "";
      const form = el("create-template-form");
      await Promise.all(
        (form.listeners.submit || []).map((fn) => fn({ preventDefault() {} }))
      );
      await view.flush();
    },
    async clickTableButton(rowIndex, label) {
      const button = this.rowButtons(rowIndex, label);
      await button.fire("click", {});
      await view.flush();
      return button;
    },
    async editAndSave(name, html, width) {
      el("edit-name").value = name;
      el("edit-html").value = html;
      /* 編輯時 edit-width 是用 template.width（number）填的，但真實
         input.value 一律是字串，而 .trim() 假設字串 —— 這裡明確轉成字串，
         讓這條路徑跟瀏覽器一致。 */
      el("edit-width").value = width === undefined ? "100" : String(width);
      el("edit-height").value = "150";
      el("edit-unit").value = "mm";
      const button = el("edit-save");
      await button.fire("click", {});
      await view.flush();
    },
    async saveSettings() {
      const button = el("save-print-settings");
      await button.fire("click", {});
      await view.flush();
    },
    async openPrintDialog() {
      const button = el("print-open");
      await button.fire("click", {});
      await view.flush();
    },
    dialogPrint: {
      visible: () => el("print-dialog").hidden === false,
      templateOptions: () =>
        el("print-template").childNodes.map((o) => o.value),
      selectedTemplate: () => selectedValue("print-template"),
      printerOptions: () => el("print-printer").childNodes.map((o) => o.value),
      selectedPrinter: () => selectedValue("print-printer"),
      sizeText: () => el("print-size").textContent,
      errorText: () => el("print-error").textContent,
      confirmDisabled: () => el("print-confirm").disabled === true,
      previewSrcdoc: () => {
        const frames = el("print-preview").childNodes.filter((n) => isTag(n, "iframe"));
        return frames.length ? frames[0].getAttribute("srcdoc") : null;
      },
      itemOptions: () => el("print-item").childNodes.map((o) => o.value),
    },
  };
}

(async () => {
  const results = [];
  const scenario = async (label, body) => {
    try {
      results.push({ label, ...(await body()) });
    } catch (err) {
      results.push({ label, error: String((err && err.stack) || err) });
    }
  };

  // 1. 設定值與範本列表都載入
  await scenario("載入設定與範本", async () => {
    const h = await mountPage({
      settings: { printer: "Xprinter XP-470E", template_id: "TPL-0003" },
    });
    await h.flush();
    return {
      unmapped: h.unmapped,
      printerOptions: h.el("setting-printer").childNodes.map((o) => o.value),
      selectedPrinter: h.selectedValue("setting-printer"),
      templateOptions: h.el("setting-template").childNodes.map((o) => o.value),
      selectedTemplate: h.selectedValue("setting-template"),
      rowTexts: h.tableRowTexts(),
      calls: h.calls,
    };
  });

  // 2. 儲存設定：預設印表機 + 預設範本
  await scenario("儲存列印設定", async () => {
    const h = await mountPage({ settings: {} });
    await h.flush();
    /* 假 DOM 的 select.value 不會跟著 selectedIndex 變，但真瀏覽器會。
       這裡用真瀏覽器的行為來驗證「存下來的是使用者看到的那個選項」——
       selectedIndex=1 就是「Xprinter XP-470E」與「TPL-0003」。 */
    h.el("setting-printer").selectedIndex = 1;
    h.el("setting-template").selectedIndex = 1;
    h.el("setting-printer").value = "Xprinter XP-470E";
    h.el("setting-template").value = "TPL-0003";
    await h.saveSettings();
    const post = h.posted("POST", "/api/settings/printing");
    return {
      unmapped: h.unmapped,
      postPath: post && post.path,
      postBody: post && post.body,
      store: { printer: h.store.printer, template_id: h.store.template_id },
      status: h.el("print-settings-status").textContent,
    };
  });

  // 3. 儲存設定失敗要顯示原因
  await scenario("儲存設定失敗", async () => {
    const h = await mountPage({ settings: {}, saveError: "無法寫入列印設定：磁碟滿" });
    await h.flush();
    await h.saveSettings();
    return {
      unmapped: h.unmapped,
      status: h.el("print-settings-status").textContent,
    };
  });

  // 4. 新增範本 → 列表多一列
  await scenario("新增範本", async () => {
    const h = await mountPage({});
    await h.flush();
    const before = h.tableRowTexts().length;
    await h.submitTemplateForm("New Label", CARD_HTML, "80", "120");
    const post = h.posted("POST", "/api/templates");
    return {
      unmapped: h.unmapped,
      postName: post && post.body.name,
      postHtml: post && post.body.html,
      postWidth: post && post.body.width,
      postHeight: post && post.body.height,
      postUnit: post && post.body.unit,
      rowsBefore: before,
      rowsAfter: h.tableRowTexts().length,
      rowTexts: h.tableRowTexts(),
    };
  });

  // 5. 新增被 validator 擋下要顯示原因且不加進列表
  await scenario("新增範本被拒", async () => {
    const h = await mountPage({
      createError: "Template 驗證失敗:\n  - 禁止的標籤: <script>",
    });
    await h.flush();
    await h.submitTemplateForm("Bad", "<html><script>x</script></html>", "", "");
    return {
      unmapped: h.unmapped,
      alerts: h.alerts,
      rows: h.tableRowTexts().length,
    };
  });

  // 6. 編輯既有範本
  await scenario("編輯範本", async () => {
    const h = await mountPage({});
    await h.flush();
    await h.clickTableButton(0, "編輯");
    const editorVisible = h.el("template-editor").hidden === false;
    const loadedName = h.el("edit-name").value;
    const loadedId = h.el("edit-id").textContent;
    await h.editAndSave("Renamed Label", CARD_HTML);
    const put = h.put("/api/templates/TPL-0002");
    return {
      unmapped: h.unmapped,
      editorVisible,
      loadedName,
      loadedId,
      putPath: put && put.path,
      putName: put && put.body.name,
      putHtml: put && put.body.html,
      putWidth: put && put.body.width,
      putHeight: put && put.body.height,
      putUnit: put && put.body.unit,
      editorHiddenAfterSave: h.el("template-editor").hidden === true,
      rowTexts: h.tableRowTexts(),
    };
  });

  // 7. 刪除範本
  await scenario("刪除範本", async () => {
    const h = await mountPage({});
    await h.flush();
    await h.clickTableButton(0, "刪除");
    return {
      unmapped: h.unmapped,
      rows: h.tableRowTexts().map((r) => r[0]),
      deletes: h.calls.filter((c) => c.startsWith("DELETE ")),
    };
  });

  // 8. 刪除可以取消
  await scenario("刪除但取消", async () => {
    const h = await mountPage({ confirmAnswer: false });
    await h.flush();
    await h.clickTableButton(0, "刪除");
    return {
      unmapped: h.unmapped,
      rows: h.tableRowTexts().length,
      deletes: h.calls.filter((c) => c.startsWith("DELETE ")).length,
    };
  });

  // 9. 範本管理頁的預覽（管理用，不是列印）
  await scenario("範本預覽", async () => {
    const h = await mountPage({});
    await h.flush();
    await h.clickTableButton(0, "預覽");
    const frames = h.el("preview-frame").childNodes.filter((n) => isTag(n, "iframe"));
    return {
      unmapped: h.unmapped,
      frameCount: frames.length,
      srcdoc: frames.length ? frames[0].getAttribute("srcdoc") : null,
      sandbox: frames.length ? frames[0].getAttribute("sandbox") : null,
      itemOptions: h.el("preview-item").childNodes.map((o) => o.value),
    };
  });

  // 10. 列印對話框套用設定值
  await scenario("設定頁開啟列印對話框", async () => {
    const h = await mountPage({
      settings: { printer: "Xprinter XP-470E", template_id: "TPL-0003" },
    });
    await h.flush();
    await h.openPrintDialog();
    return {
      unmapped: h.unmapped,
      visible: h.dialogPrint.visible(),
      templateOptions: h.dialogPrint.templateOptions(),
      selectedTemplate: h.dialogPrint.selectedTemplate(),
      printerOptions: h.dialogPrint.printerOptions(),
      selectedPrinter: h.dialogPrint.selectedPrinter(),
      itemOptions: h.dialogPrint.itemOptions(),
      sizeText: h.dialogPrint.sizeText(),
      errorText: h.dialogPrint.errorText(),
      confirmDisabled: h.dialogPrint.confirmDisabled(),
      previewSrcdoc: h.dialogPrint.previewSrcdoc(),
    };
  });

  // 11. 沒有設定值時退回第一個範本 + Windows 預設印表機
  await scenario("沒有設定值的列印對話框", async () => {
    const h = await mountPage({ settings: {} });
    await h.flush();
    await h.openPrintDialog();
    return {
      unmapped: h.unmapped,
      selectedTemplate: h.dialogPrint.selectedTemplate(),
      selectedPrinter: h.dialogPrint.selectedPrinter(),
    };
  });

  // 12. 沒有印表機要說清楚
  await scenario("設定頁找不到印表機", async () => {
    const h = await mountPage({ printers: [] });
    await h.flush();
    await h.openPrintDialog();
    return {
      unmapped: h.unmapped,
      status: h.el("print-settings-status").textContent,
      settingPrinterOption: h.el("setting-printer").childNodes.map((o) => o.textContent),
      dialogError: h.dialogPrint.errorText(),
      confirmDisabled: h.dialogPrint.confirmDisabled(),
    };
  });

  // 13. 範本管理頁不應該出現 Template 編輯以外的列印 CRUD
  await scenario("設定頁範本列操作", async () => {
    const h = await mountPage({});
    await h.flush();
    const labels = h.el("template-rows").childNodes.map((row) =>
      row.querySelectorAll("button").map((b) => b.textContent)
    );
    return { unmapped: h.unmapped, labels };
  });

  // 14. 沒有任何範本時要明說，不要空白表格
  await scenario("沒有範本", async () => {
    const h = await mountPage({ initialTemplates: [] });
    await h.flush();
    return {
      unmapped: h.unmapped,
      rows: h.tableRowTexts(),
      templateOptions: h.el("setting-template").childNodes.map((o) => o.value),
    };
  });

  // 15. 範本預覽失敗要顯示原因
  await scenario("範本預覽失敗", async () => {
    const h = await mountPage({ previewError: "Template 渲染失敗" });
    await h.flush();
    await h.clickTableButton(0, "預覽");
    return {
      unmapped: h.unmapped,
      frameCount: h.el("preview-frame").childNodes
        .filter((n) => isTag(n, "iframe")).length,
      emptyText: h.el("preview-empty").textContent,
    };
  });

  // 16. 編輯既有範本時欄位要真的帶入（含尺寸），不是空白
  await scenario("編輯帶入既有內容", async () => {
    const h = await mountPage({});
    await h.flush();
    await h.clickTableButton(1, "編輯");
    return {
      unmapped: h.unmapped,
      editorVisible: h.el("template-editor").hidden === false,
      id: h.el("edit-id").textContent,
      name: h.el("edit-name").value,
      htmlHasBind: String(h.el("edit-html").value).includes("data-bind"),
      width: h.el("edit-width").value,
      height: h.el("edit-height").value,
      unit: h.el("edit-unit").value,
      widthIsString: typeof h.el("edit-width").value === "string",
    };
  });

  // 17. 編輯被 validator 擋下要顯示原因且編輯器保持開啟
  await scenario("編輯範本被拒", async () => {
    const h = await mountPage({ updateError: "Template 驗證失敗:\n  - 禁止的標籤: <script>" });
    await h.flush();
    await h.clickTableButton(0, "編輯");
    await h.editAndSave("Bad", "<html><script>x</script></html>");
    return {
      unmapped: h.unmapped,
      alerts: h.alerts,
      stillOpen: h.el("template-editor").hidden === false,
      rowName: h.tableRowTexts()[0][1],
    };
  });

  process.stdout.write(JSON.stringify(results, null, 2));
})();