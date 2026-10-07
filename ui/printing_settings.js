/* 範本管理 + 列印設定（設定 → 列印）。
 *
 * 這一頁負責長期設定：
 *   - 預設印表機、預設範本（寫進 tools/print_config.local.json）
 *   - 範本管理：新增 / 預覽 / 編輯 / 刪除
 *
 * 商品頁只保留「挑範本 → 看預覽 → 列印」，不負責管理 Template。
 * 列印對話框本身在 ui/print_dialog.js，兩個頁面共用。
 *
 * 範本的驗證與渲染都在 server（shop/template_renderer.py），
 * 這裡不重做任何 Template 邏輯。
 */

const JSON_HEADERS = { "Content-Type": "application/json" };

function el(id) { return document.getElementById(id); }

function formatDate(iso) {
    if (!iso) return "—";
    return i18nFormatDateTime(iso);
}

async function api(path, options) {
    const response = await fetch("/api" + path, options);
    let body = null;
    const text = await response.text();
    if (text) {
        try {
            body = JSON.parse(text);
        } catch (err) {
            body = text;
        }
    }
    if (!response.ok) {
        const detail = body && body.detail;
        throw new Error(
            typeof detail === "string" ? detail : "HTTP " + response.status
        );
    }
    return body;
}

function alertBox(message) {
    if (typeof window.alert === "function") window.alert(message);
}

/* print_dialog.js 需要這個介面；共用同一個 api()，不寫兩份 fetch。 */
printDialogApi = {
    get: (path) => api(path),
    post: (path, body) => api(path, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
    }),
};

/* ---------------------------------------------------------------------
 * 列印設定
 * ------------------------------------------------------------------- */

function setSettingStatus(message, kind) {
    const box = el("print-settings-status");
    box.textContent = message || "";
    box.className = "status" + (kind ? " status-" + kind : "");
}

async function loadPrintSettings() {
    const settings = await api("/settings/printing");
    if (settings.error) {
        /* settings.error 是後端寫的訊息（已經是繁體中文，因為那是 API
           的錯誤內容，不是 UI 翻譯）。這裡只能原樣顯示 —— 要翻譯就會
           需要 server 端也做 i18n，那是資料層的改動，不屬於這一輪。
           前綴「設定檔有問題」才是 UI 文字，走翻譯。 */
        setSettingStatus(
            t("printing.config_error", { message: settings.error }), "bad"
        );
    }
    return settings;
}

async function loadPrinterChoices() {
    /* 讀不到清單與「清單是空的」是兩件事，錯誤訊息要分開。 */
    let printers;
    try {
        printers = await api("/printers");
    } catch (err) {
        const select = el("setting-printer");
        select.replaceChildren(
            optionNode("", t("printing.printer_read_failed_option"))
        );
        throw new Error(t("printing.printer_list_failed", { message: err.message }));
    }
    const select = el("setting-printer");
    if (!printers.length) {
        /* 顯示明確訊息，不要空白下拉視窗。 */
        select.replaceChildren(optionNode("", t("printing.no_printer_option")));
        return printers;
    }
    select.replaceChildren(
        ...printers.map((printer) =>
            optionNode(
                printer.name,
                printer.is_default
                    ? printer.name + t("print.printer_is_default_suffix")
                    : printer.name
            )
        )
    );
    return printers;
}

function optionNode(value, text) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = text;
    return node;
}

async function renderPrintSettings() {
    const [settings, printers] = await Promise.all([
        loadPrintSettings(),
        loadPrinterChoices(),
    ]);

    /* 範本下拉由 loadTemplates 填（同一份清單，避免兩處不一致）。 */
    applyTemplateChoice(settings.template_id);
    applyPrinterChoice(settings.printer, printers);
    setSettingStatus("", null);
}

function applyPrinterChoice(name, printers) {
    const select = el("setting-printer");
    if (!printers || !printers.length) return;
    const index = printers.findIndex((printer) => printer.name === name);
    select.selectedIndex = index >= 0 ? index : 0;
}

function applyTemplateChoice(id) {
    const select = el("setting-template");
    const options = Array.from(select.childNodes);
    if (!options.length) return;
    const index = options.findIndex((option) => option.value === id);
    select.selectedIndex = index >= 0 ? index : 0;
}

async function savePrintSettings() {
    const button = el("save-print-settings");
    button.disabled = true;
    try {
        await api("/settings/printing", {
            method: "POST",
            headers: JSON_HEADERS,
            body: JSON.stringify({
                printer: el("setting-printer").value || null,
                template_id: el("setting-template").value || null,
            }),
        });
        setSettingStatus(t("printing.saved"), "ok");
    } catch (err) {
        setSettingStatus(t("printing.save_failed", { message: err.message }), "bad");
    } finally {
        button.disabled = false;
    }
}

/* ---------------------------------------------------------------------
 * 範本管理
 * ------------------------------------------------------------------- */

function templateTableRow(template) {
    const row = document.createElement("tr");
    const add = (text) => {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.appendChild(cell);
    };
    add(template.id);
    add(template.name);
    add(template.width ? `${template.width}` : t("common.none"));
    add(template.height ? `${template.height}` : t("common.none"));
    add(formatDate(template.created_at));
    add(formatDate(template.updated_at));

    const actions = document.createElement("td");
    const wrap = document.createElement("div");
    wrap.className = "row-actions";
    wrap.appendChild(rowButton(
        t("template.action_preview"), "secondary", () => openPreview(template.id)
    ));
    wrap.appendChild(
        rowButton(t("template.action_edit"), "", () => editTemplate(template))
    );
    wrap.appendChild(
        rowButton(t("template.action_delete"), "danger", () => deleteTemplate(template.id))
    );
    actions.appendChild(wrap);
    row.appendChild(actions);
    return row;
}

function rowButton(label, kind, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (kind) button.className = kind;
    button.addEventListener("click", onClick);
    return button;
}

async function loadTemplates() {
    const list = await api("/templates?limit=200");
    const tbody = el("template-rows");
    if (!list.length) {
        const empty = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 7;
        cell.textContent = t("template.empty");
        empty.appendChild(cell);
        tbody.replaceChildren(empty);
    } else {
        tbody.replaceChildren(...list.map(templateTableRow));
    }
    /* 設定頁的「預設範本」下拉跟著同一份清單走。 */
    const select = el("setting-template");
    const previous = select.value;
    select.replaceChildren(
        ...list.map((template) =>
            optionNode(template.id, `${template.name} (${template.id})`)
        )
    );
    if (previous) applyTemplateChoice(previous);
    return list;
}

/* ---------------------------------------------------------------------
 * 新增範本
 * ------------------------------------------------------------------- */

el("create-template-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = el("template-name").value.trim();
    const input = el("template-html");
    const width = el("template-width").value.trim();
    const height = el("template-height").value.trim();
    const unit = el("template-unit").value.trim() || "mm";
    if (!name || !input.value.trim()) {
        alertBox(t("template.create_needs_name"));
        return;
    }
    try {
        await api("/templates", {
            method: "POST",
            headers: JSON_HEADERS,
            body: JSON.stringify({
                name,
                html: input.value,
                width: width ? parseFloat(width) : null,
                height: height ? parseFloat(height) : null,
                unit,
            }),
        });
        el("template-name").value = "";
        input.value = "";
        await loadTemplates();
        setSettingStatus(t("template.created"), "ok");
    } catch (err) {
        alertBox(t("template.create_failed", { message: err.message }));
    }
});

/* ---------------------------------------------------------------------
 * 編輯 / 刪除
 * ------------------------------------------------------------------- */

function editTemplate(template) {
    el("edit-id").textContent = template.id;
    el("edit-name").value = template.name;
    el("edit-html").value = template.html;
    /* 一律轉成字串：真實 input.value 永遠是字串，而下面的讀取端會呼叫
       .trim()，塞 number 進去會在存檔時拋 TypeError。 */
    el("edit-width").value = template.width === null || template.width === undefined
        ? "" : String(template.width);
    el("edit-height").value = template.height === null || template.height === undefined
        ? "" : String(template.height);
    el("edit-unit").value = template.unit || "mm";
    /* 用 hidden 屬性而不是 .hidden class：markup 初始就是 hidden 屬性，
       兩邊一致才不會出現「按了編輯但畫面沒開」。 */
    el("template-editor").hidden = false;
}

el("edit-cancel").addEventListener("click", () => {
    el("template-editor").hidden = true;
});

el("edit-save").addEventListener("click", async () => {
    const id = el("edit-id").textContent;
    const width = el("edit-width").value.trim();
    const height = el("edit-height").value.trim();
    try {
        await api("/templates/" + encodeURIComponent(id), {
            method: "PUT",
            headers: JSON_HEADERS,
            body: JSON.stringify({
                name: el("edit-name").value.trim(),
                html: el("edit-html").value,
                width: width ? parseFloat(width) : null,
                height: height ? parseFloat(height) : null,
                unit: el("edit-unit").value.trim() || "mm",
            }),
        });
        el("template-editor").hidden = true;
        await loadTemplates();
        setSettingStatus(t("template.updated"), "ok");
    } catch (err) {
        alertBox(t("template.update_failed", { message: err.message }));
    }
});

function deleteTemplate(id) {
    const question = t("template.delete_confirm", { id });
    if (typeof window.confirm === "function" && !window.confirm(question)) return;
    api("/templates/" + encodeURIComponent(id), { method: "DELETE" })
        .then(async () => {
            await loadTemplates();
            setSettingStatus(t("template.deleted"), "ok");
        })
        .catch((err) => alertBox(t("template.delete_failed", { message: err.message })));
}

/* ---------------------------------------------------------------------
 * 範本預覽（管理用，看渲染結果，不是列印）
 * ------------------------------------------------------------------- */

async function openPreview(templateId) {
    /* 範本預覽區固定顯示，不需要開關。原先的 el("template-preview")
       這裡不存在（那個 id 從來沒寫進 markup），而那一行讓整支 script
       的 IIFE 中斷 —— 範本列表永遠不載入，畫面一片空白且沒有錯誤訊息。
       預覽區的內容由 preview-frame / preview-empty 這兩個節點表達。 */
    el("preview-frame").replaceChildren();
    try {
        const items = await api("/items?limit=200");
        const select = el("preview-item");
        select.replaceChildren(
            ...items.map((item) =>
                optionNode(
                    item.id,
                    `${item.id} - ${item.name || t("printing.no_item_name")}`
                )
            )
        );
        if (items.length) {
            el("preview-template-id").textContent = templateId;
            await renderTemplatePreview();
        } else {
            el("preview-empty").textContent = t("template.preview_empty");
            el("preview-empty").classList.remove("hidden");
        }
    } catch (err) {
        el("preview-empty").textContent = t("template.preview_failed", {
            message: err.message,
        });
        el("preview-empty").classList.remove("hidden");
    }
}

async function renderTemplatePreview() {
    const itemId = el("preview-item").value;
    const templateId = el("preview-template-id").textContent;
    el("preview-empty").classList.add("hidden");
    try {
        const result = await api(
            `/templates/${encodeURIComponent(templateId)}/preview`,
            {
                method: "POST",
                headers: JSON_HEADERS,
                body: JSON.stringify({ item_id: itemId }),
            }
        );
        const frame = document.createElement("iframe");
        frame.setAttribute("srcdoc", result.html);
        /* Template 內容不可信：sandbox 空值，無 script、無 same-origin。 */
        frame.setAttribute("sandbox", "");
        frame.style.width = "100%";
        frame.style.border = "none";
        frame.style.minHeight = "320px";
        el("preview-frame").replaceChildren(frame);
    } catch (err) {
        el("preview-frame").replaceChildren();
        el("preview-empty").textContent = t("template.preview_failed", { message: err.message });
        el("preview-empty").classList.remove("hidden");
    }
}

el("preview-item").addEventListener("change", renderTemplatePreview);

/* ---------------------------------------------------------------------
 * Init
 * ------------------------------------------------------------------- */

el("save-print-settings").addEventListener("click", savePrintSettings);
el("print-open").addEventListener("click", () => printOpenDialog());
printBind();

/* 語言切換時重畫這一頁的動態文字：範本表格的按鈕標籤、設定狀態訊息、
   印表機與範本下拉的選項文字。它們都由 JS 產生，不在 markup 的
   data-i18n 範圍內。lastTemplates 記住上次的清單，重畫才有料。 */
let lastTemplates = [];
i18nSubscribe(() => {
    if (lastTemplates.length) {
        el("template-rows").replaceChildren(...lastTemplates.map(templateTableRow));
    }
    loadPrinterChoices().catch(() => {});
});

(async () => {
    i18nInit();
    /* 印表機讀不到時要把原因放在自己的錯誤槽，不要跟「已儲存」共用
       status —— 否則使用者只會看到一句籠統的失敗訊息。 */
    const errors = [];
    try {
        lastTemplates = await loadTemplates();
    } catch (err) {
        errors.push(t("print.templates_failed", { message: err.message }));
    }
    try {
        await renderPrintSettings();
    } catch (err) {
        errors.push(err.message);
    }
    const box = el("print-settings-error");
    box.hidden = errors.length === 0;
    box.textContent = errors.join(t("common.list_separator"));
})();