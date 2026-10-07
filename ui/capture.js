/* 連續拍照：直接開相機 → 一張一張累積 → 完成後預覽本批 → 建檔。

   「取得照片」這一件事沿用既有的 <input type="file" capture> 相機
   入口（capture="environment" 讓手機直接進相機，不用再選相機或
   相簿）；批次只在記憶體裡累積，按「建檔」才一次走既有的多照片
   流程，不另做第二套 pipeline：

     POST /api/inbox/photos   整批上傳到 inbox（既有端點）
     GET  /api/inbox  前後差集 = 這一批的相對路徑
     POST /api/inbox/intake   既有的一鍵建檔：
                              Item + Observation + 照片歸檔
     導向 /items/<id>?ai=1    沿用商品頁既有的 AI 自動填入

   取消整批只是把記憶體裡的批次丟掉 —— 什麼都還沒上傳，
   不會有半成品 Item，inbox 也不會留下檔案。 */

const cameraInput = document.getElementById("camera-input");
const shutter = document.getElementById("shutter");
const strip = document.getElementById("strip");
const count = document.getElementById("count");
const captureSec = document.getElementById("capture-sec");
const previewSec = document.getElementById("preview-sec");
const grid = document.getElementById("grid");
const gridEmpty = document.getElementById("grid-empty");
const previewCount = document.getElementById("preview-count");
const finishBtn = document.getElementById("finish");
const cancelBtn = document.getElementById("cancel");
const buildBtn = document.getElementById("build");
const continueBtn = document.getElementById("continue");
const discardBtn = document.getElementById("discard");

/* 這一批照片：還在記憶體裡，沒有上傳。 */
let batch = [];

function objectUrl(file) {
  return typeof URL.createObjectURL === "function"
    ? URL.createObjectURL(file) : "";
}

function revoke(url) {
  if (url && typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(url);
  }
}

function renderCount() {
  count.textContent = t("capture.taken_count", { count: batch.length });
  finishBtn.disabled = batch.length === 0;
}

function thumb(entry) {
  const figure = el("figure", { class: "cell" });
  figure.appendChild(
    el("img", { src: entry.url, alt: entry.file.name, loading: "lazy" })
  );
  return figure;
}

/* 拍攝區的縮圖：只顯示最近幾張，和 inbox 分組卡片同一個做法 */
function renderStrip() {
  clear(strip);
  batch.slice(-8).forEach((entry) => strip.appendChild(thumb(entry)));
  const extra = batch.length - 8;
  if (extra > 0) {
    strip.appendChild(el("div", { class: "cell more", text: "+" + extra }));
  }
}

function batchCell(entry, index) {
  return el("figure", {}, [
    el("img", { src: entry.url, alt: entry.file.name, loading: "lazy" }),
    el("button", {
      class: "remove", type: "button", "data-index": index,
      text: "✕", title: t("capture.remove_photo"),
      onclick: () => removeAt(index),
    }),
  ]);
}

function renderGrid() {
  clear(grid);
  batch.forEach((entry, index) => grid.appendChild(batchCell(entry, index)));
  gridEmpty.hidden = batch.length > 0;
  previewCount.textContent = batch.length
    ? t("capture.photo_count", { count: batch.length }) : "";
  buildBtn.disabled = batch.length === 0;
}

function renderAll() {
  renderCount();
  renderStrip();
  renderGrid();
}

function showPreview() {
  captureSec.hidden = true;
  previewSec.hidden = false;
  renderGrid();
}

function showCapture() {
  previewSec.hidden = true;
  captureSec.hidden = false;
  renderStrip();
}

function removeAt(index) {
  const entry = batch[index];
  if (!entry) return;
  batch.splice(index, 1);
  revoke(entry.url);
  renderAll();
}

/* ------------------------------------------------------------ 相機 */

/* 觸發路徑只有這一條。和 inbox 同一個道理：#shutter 是 button 不是
   label —— label 包住 file input 時，點 label 會由瀏覽器原生觸發
   input，再疊上 JS 的 click() 就是雙重觸發，實機測到 file picker
   被開兩次又立刻關掉、change 事件沒發生。 */
shutter.addEventListener("click", () => cameraInput.click());

cameraInput.addEventListener("change", () => {
  /* 先把 FileList 複製成 Array 再清 input —— 順序反過來會拿到 0
     張。input.files 是「活的」FileList：value = "" 會清空 selected
     files，而 getter 在清單沒變時回傳同一個物件（inbox.js 踩過的
     坑，這裡照做）。 */
  const picked = Array.from(cameraInput.files || []);
  cameraInput.value = "";   // 清掉，讓下一張也能觸發 change
  if (!picked.length) return;
  /* 拍完立即回到可繼續拍攝狀態：批次累積、快門保持可用，
     不用重新選相機（capture 屬性已經把相機釘死了） */
  picked.forEach((file) => batch.push({ file, url: objectUrl(file) }));
  renderAll();
});

/* ------------------------------------------------------------ 批次 */

finishBtn.addEventListener("click", showPreview);
continueBtn.addEventListener("click", showCapture);

/* 取消：記憶體裡的批次還沒上傳，丟掉就什麼都不剩。 */
function discard() {
  batch.forEach((entry) => revoke(entry.url));
  batch = [];
  renderAll();
  window.location.href = "/";
}
cancelBtn.addEventListener("click", discard);
discardBtn.addEventListener("click", discard);

/* 建檔：整批交給既有的多照片流程（upload → intake → AI）。 */
async function build() {
  if (!batch.length) return;
  buildBtn.disabled = true;
  showError("");
  try {
    /* 上傳前先記下 inbox 現有清單 */
    const before = new Set(
      (await api("/api/inbox")).entries.map((entry) => entry.relative)
    );

    /* 整批一次上傳：既有端點，multipart 欄位名 files */
    const body = new FormData();
    batch.forEach((entry) => body.append("files", entry.file, entry.file.name));
    await api("/api/inbox/photos", { method: "POST", body });

    /* 前後差集 = 這一批在 inbox 裡的相對路徑。
       不用自己猜檔名：同名時後端會加流水號（image-2.jpg…），
       差集才靠得住。注意這裡假設上傳前後沒有別人同時上傳
       （單人使用的區網工具，這個窗口極短）。 */
    const after = (await api("/api/inbox")).entries.map((e) => e.relative);
    const fresh = after.filter((relative) => !before.has(relative));
    if (!fresh.length) {
      showError(t("capture.missing_after_upload"));
      return;
    }

    /* 既有的一鍵建檔：Item + Observation + 照片歸檔，全有全無 */
    const done = await api("/api/inbox/intake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: fresh, kind: "intake" }),
    });
    if (!done.item_id) {
      window.location.href = "/";
      return;
    }

    /* 導向商品頁，?ai=1 讓商品頁沿用同一條 AI 流程自動分析這批照片 */
    window.location.href =
      "/items/" + encodeURIComponent(done.item_id) + "?ai=1";
  } catch (err) {
    /* 到這裡照片可能已經在 inbox 裡了 —— 和 inbox.js 同一個道理，
       說「上傳失敗」會讓人重傳一遍。告訴人去 Inbox 收。 */
    showError(t("capture.build_failed", { message: err.message }));
  } finally {
    buildBtn.disabled = false;
  }
}
buildBtn.addEventListener("click", build);

/* 初始畫面：拍攝視圖（假 DOM 不解析 HTML 的 hidden 屬性，
   這裡明確設一次，瀏覽器上剛好與 markup 一致）。
   i18nInit() 排在 renderAll() 之前 —— renderCount() 會呼叫 t()。 */
i18nInit();
renderAll();
showCapture();
