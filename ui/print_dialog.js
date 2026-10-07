/* 共用列印對話框。
 *
 * 商品頁與設定頁都要「選範本 → 看預覽 → 選印表機 → 列印 1 份」，
 * 所以這段抽成一個模組，只負責對話框本身：
 *
 *   - 從 /api/settings/printing 讀預設值（預設範本、預設印表機）
 *   - 從 /api/templates 讀範本清單
 *   - 從 /api/printers 讀 Windows 印表機
 *   - 切換範本 → 重新呼叫 /print-preview → 更新預覽
 *   - 送出 /print
 *
 * 刻意不碰 Template 的建立／編輯／移除：那是範本管理的範疇，屬於
 * 設定頁。商品頁只挑「用哪一個範本印」，不該出現 Template CRUD。
 *
 * 預覽的來源是 /print-preview 回傳的 html —— 那就是送進 PDF 的那一份
 * （server 端共用 shop/api.py 的 _print_html），所以顯示的與列印的
 * 必然一致。這裡不自己組預覽。
 *
 * 失敗一律顯示在 #print-error，不留空白：找不到印表機、讀不到清單、
 * 載入預覽失敗，使用者都要看得到真正原因。
 *
 * 依賴的 DOM（id）由各頁提供，缺哪個就在哪個頁面壞掉，不做防禦。
 */

/* 呼叫端要提供 printDialogApi（.get/.post），其餘由這個模組維護。 */
let printDialogApi = null;

/* 對話框是否已經載入完成（列印鈕能否按）。 */
let printDialogReady = false;
/* 目前選的範本。切換範本只是換一個變數，不修改 Template 本身。 */
let printDialogTemplateId = null;
let printDialogItemId = null;
/* 目前選的印表機。跟範本一樣存在自己的變數，不靠 select.value ——
   送出時要確保帶到的是使用者真的選的那一台。 */
let printDialogPrinter = null;
let printDialogTemplates = [];
/* 印表機不可用的原因。存起來是因為預覽載入成功後會重寫錯誤訊息，
   沒有這一行「找不到印表機」就會被蓋掉。 */
let printDialogPrinterError = "";
/* 一次載入的結果：{ items, printers }。範本不放這裡，因為範本清單
   同時要給範本管理用。 */
let printDialogState = { items: [], printers: [] };

function printEl(id) { return document.getElementById(id); }

function printError(message) {
    const box = printEl("print-error");
    if (box) box.textContent = message || "";
}

function printInfo(message) {
    const box = printEl("print-size");
    if (box) box.textContent = message || "";
}

function printFail(message) {
    printError(message);
    printInfo("");
}

/* ---------------------------------------------------------------------
 * 載入來源
 * ------------------------------------------------------------------- */

/* 範本清單。只取要顯示的欄位，不帶 HTML —— 商品頁不需要看 Template 原始碼。 */
async function printLoadTemplates() {
    const list = await printDialogApi.get("/templates?limit=200");
    return (list || []).map((template) => ({
        id: template.id,
        name: template.name,
        width: template.width,
        height: template.height,
        unit: template.unit || "",
    }));
}

async function printLoadPrinters() {
    return printDialogApi.get("/printers");
}

async function printLoadSettings() {
    try {
        return await printDialogApi.get("/settings/printing");
    } catch (err) {
        /* 讀不到設定不該擋住列印 —— 使用者還是可以現場選。 */
        printError(t("print.settings_failed", { message: err.message }));
        return { printer: null, template_id: null };
    }
}

async function printLoadItems() {
    return printDialogApi.get("/items?limit=200");
}

/* ---------------------------------------------------------------------
 * 填選單
 * ------------------------------------------------------------------- */

function fillTemplateOptions(selectedId) {
    const select = printEl("print-template");
    if (!select) return;
    if (!printDialogTemplates.length) {
        select.replaceChildren(optionNode("", t("printing.no_template_option")));
        printDialogTemplateId = null;
        return;
    }
    /* template.name / id / width / height / unit 全是使用者自己的資料，
       原樣顯示。只有包裝用的分隔符號與「尺寸」格式走翻譯。 */
    const options = printDialogTemplates.map((template) => {
        const label = template.width && template.height
            ? `${template.name} (${template.id}) `
                + t("template.dimensions", {
                    width: template.width, height: template.height,
                    unit: template.unit,
                })
            : `${template.name} (${template.id})`;
        return optionNode(template.id, label);
    });
    select.replaceChildren(...options);

    /* 預設選擇：設定裡的預設範本；它不存在時退回第一個。 */
    const wanted = selectedId || printDialogTemplates[0].id;
    const index = printDialogTemplates.findIndex((t) => t.id === wanted);
    const chosen = index >= 0 ? index : 0;
    select.selectedIndex = chosen;
    /* 選擇狀態存在自己的變數，不靠 select.value。某些環境（以及測試用的
       假 DOM）不會從 selectedIndex 同步 value，那樣會讓「選了哪個範本」
       變成空字串，預覽與列印就送不出 template_id。 */
    printDialogTemplateId = printDialogTemplates[chosen].id;
}

function fillPrinterOptions(selectedName) {
    const select = printEl("print-printer");
    if (!select) return;
    printDialogPrinters = printDialogState.printers || [];

    if (!printDialogPrinters.length) {
        /* 空白下拉視窗會讓人以為當機，而不是沒有印表機。 */
        const label = t(printDialogState.printerError
            ? "printing.printer_read_failed_option"
            : "printing.no_printer_option");
        select.replaceChildren(optionNode("", label));
        /* 清單讀不到（server 缺依賴）與真的沒印表機是兩件事，顯示的
           訊息要分開：前者要查 server，後者要在 Windows 加印表機。 */
        printDialogPrinterError = printDialogState.printerError
            || t("print.no_printer");
        printFail(printDialogPrinterError);
        return;
    }
    if (!printDialogState.printerError) printDialogPrinterError = "";
    /* printer.name 是 Windows 的實際印表機名稱（資料），原樣顯示。
       只有「（Windows 預設）」這個標記走翻譯。 */
    const options = printDialogPrinters.map((printer) =>
        optionNode(
            printer.name,
            printer.is_default
                ? printer.name + t("print.printer_is_default_suffix")
                : printer.name
        )
    );
    select.replaceChildren(...options);

    /* 預設選擇：設定裡的預設印表機 → Windows 預設 → 第一台。 */
    const wanted = selectedName
        || (printDialogPrinters.find((p) => p.is_default) || {}).name
        || printDialogPrinters[0].name;
    const index = printDialogPrinters.findIndex((p) => p.name === wanted);
    const chosen = index >= 0 ? index : 0;
    select.selectedIndex = chosen;
    printDialogPrinter = printDialogPrinters[chosen].name;
    printEl("print-confirm").disabled = false;
}

function fillItemOptions() {
    const select = printEl("print-item");
    if (!select) return;
    const items = printDialogState.items || [];
    if (!items.length) {
        select.replaceChildren(optionNode("", t("printing.no_item_option")));
        return;
    }
    /* item.id / item.name 是資料，原樣顯示；沒有名字時才用 UI 補的提示。 */
    select.replaceChildren(
        ...items.map((item) =>
            optionNode(
                item.id,
                `${item.id} - ${item.name || t("printing.no_item_name")}`
            )
        )
    );
    /* 商品頁：printOpenDialog 已帶入本頁商品，固定用它。
       設定頁：沒有帶入就選第一個，否則對話框會卡在「請先選擇商品」。 */
    const index = items.findIndex((item) => item.id === printDialogItemId);
    const chosen = index >= 0 ? index : 0;
    select.selectedIndex = chosen;
    if (index === -1) printDialogItemId = items[chosen].id;
}

function optionNode(value, text) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = text;
    return node;
}

/* ---------------------------------------------------------------------
 * 開啟／關閉
 * ------------------------------------------------------------------- */

/* itemId 為 null 表示商品頁（商品固定）；設定頁傳入選項讓使用者挑。 */
async function printOpenDialog(itemId) {
    printDialogReady = false;
    /* 用 hidden 屬性而不是 .hidden class：item.js 與 settings.html 都用
       hidden，app.css 也沒有會蓋掉它的 display 規則，兩邊一致。 */
    printEl("print-dialog").hidden = false;
    printError("");
    printInfo(t("common.loading"));
    printEl("print-confirm").disabled = true;
    printEl("print-preview").replaceChildren();

    printDialogItemId = itemId || printDialogItemId;

    let printersError = "";
    const [settings, templates, printers, items] = await Promise.all([
        printLoadSettings(),
        printLoadTemplates().catch((err) => {
            printFail(t("print.templates_failed", { message: err.message }));
            return [];
        }),
        printLoadPrinters().catch((err) => {
            printersError = t("print.printers_failed", { message: err.message });
            return [];
        }),
        printLoadItems().catch(() => []),
    ]);

    printDialogTemplates = templates;
    /* printers 可能是「清單本身讀不到」。那時要把真正的錯誤原因帶到
       畫面上，而不是顯示成「找不到印表機」—— 兩者的處置完全不同：
       前者是 server 缺依賴，後者是這台機器真的沒裝印表機。 */
    printDialogState = { items, printers, printerError: printersError };
    printDialogPrinterError = printersError || "";

    fillItemOptions();
    fillTemplateOptions(settings.template_id);
    fillPrinterOptions(settings.printer);

    if (!printDialogTemplateId) {
        printFail(t("print.no_template"));
        return;
    }
    await printRefreshPreview();
}

function printCloseDialog() {
    printEl("print-dialog").hidden = true;
}

/* ---------------------------------------------------------------------
 * 預覽
 * ------------------------------------------------------------------- */

async function printRefreshPreview() {
    const itemId = printDialogItemId;
    const templateId = printDialogTemplateId;
    if (!itemId || !templateId) {
        printFail(t("print.need_selection"));
        return;
    }
    printEl("print-confirm").disabled = true;
    printInfo(t("print.refreshing"));
    try {
        /* 只重新取得預覽，不碰 Template 本身 —— 切換範本不是修改範本。 */
        const result = await printDialogApi.post(
            `/templates/${encodeURIComponent(templateId)}/print-preview`,
            { item_id: itemId }
        );
        renderPrintPreview(result.html);
        printInfo(t("print.size", {
            width: Number(result.width_mm).toFixed(1),
            height: Number(result.height_mm).toFixed(1),
        }));
        printDialogReady = true;
        /* 預覽好了不代表能列印：沒有印表機時原因要留著，不能被
           預覽的成功訊息蓋掉，否則使用者只看到一個按不了的按鈕。 */
        printEl("print-confirm").disabled = !printDialogPrinters.length;
        if (!printDialogPrinters.length) {
            printError(printDialogPrinterError);
        } else {
            printError("");
        }
    } catch (err) {
        printFail(t("print.preview_failed", { message: err.message }));
    }
}

function renderPrintPreview(html) {
    const box = printEl("print-preview");
    const frame = document.createElement("iframe");
    frame.setAttribute("srcdoc", html);
    /* Template 內容不可信：sandbox 空值 = opaque origin、無 script。 */
    frame.setAttribute("sandbox", "");
    frame.style.width = "100%";
    frame.style.border = "none";
    frame.style.minHeight = "240px";
    box.replaceChildren(frame);
}

/* ---------------------------------------------------------------------
 * 送出
 * ------------------------------------------------------------------- */

async function printSubmit() {
    if (!printDialogReady || !printDialogItemId || !printDialogTemplateId) {
        printFail(t("print.need_selection"));
        return;
    }
    const button = printEl("print-confirm");
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = t("print.submitting");
    printError("");
    printInfo(t("print.sending"));
    try {
        const result = await printDialogApi.post(
            `/templates/${encodeURIComponent(printDialogTemplateId)}/print`,
            {
                item_id: printDialogItemId,
                printer: printDialogPrinter || null,
            }
        );
        /* result.printer 是 Windows 的實際印表機名稱（資料），原樣顯示。 */
        printInfo(t("print.sent", {
            printer: result.printer,
            width: Number(result.width_mm).toFixed(1),
            height: Number(result.height_mm).toFixed(1),
        }));
    } catch (err) {
        printFail(t("print.submit_failed", { message: err.message }));
    } finally {
        button.disabled = !printDialogReady;
        button.textContent = originalLabel;
    }
}

/* ---------------------------------------------------------------------
 * 綁定
 * ------------------------------------------------------------------- */

function printBind() {
    printEl("print-close").addEventListener("click", printCloseDialog);

    /* 語言切換時重畫對話框裡「由 JS 產生」的文字：選項標籤、尺寸、
       錯誤訊息。這些不在 markup 的 data-i18n 範圍內（每次開啟都重新
       產生），所以要重新渲染一次，而不是等使用者再開一次對話框。 */
    i18nSubscribe(() => {
        if (!printEl("print-dialog") || printEl("print-dialog").hidden) return;
        if (printDialogState.items) fillItemOptions();
        if (printDialogTemplates.length) fillTemplateOptions(printDialogTemplateId);
        if (printDialogState.printers) fillPrinterOptions(printDialogPrinter);
    });

    /* 切換範本 → 更新預覽（不改 Template）。 */
    const templateSelect = printEl("print-template");
    if (templateSelect) {
        templateSelect.addEventListener("change", async () => {
            printDialogTemplateId = templateSelect.value;
            await printRefreshPreview();
        });
    }
    /* 商品頁的商品是固定的；設定頁才有下拉可以換。 */
    const itemSelect = printEl("print-item");
    if (itemSelect) {
        itemSelect.addEventListener("change", async () => {
            printDialogItemId = itemSelect.value;
            await printRefreshPreview();
        });
    }
    const printerSelect = printEl("print-printer");
    if (printerSelect) {
        printerSelect.addEventListener("change", () => {
            printDialogPrinter = printerSelect.value;
        });
    }
    printEl("print-confirm").addEventListener("click", printSubmit);
}

if (typeof i18nSubscribe === "function") {
    i18nSubscribe(() => {
        const dialog = printEl("print-dialog");
        if (dialog && !dialog.hidden) {
            printRefreshPreview().catch(() => {});
        }
    });
}