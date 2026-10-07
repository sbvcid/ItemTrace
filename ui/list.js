/* 商品列表：搜尋、篩選、分頁。搜尋邏輯完全交給後端，前端不自己比對。 */

const PAGE_SIZE = 30;
const STATUSES = ["active", "archived", "void"];

const rows = document.getElementById("rows");
const emptyBox = document.getElementById("empty");
const errorBox = document.getElementById("error");
const countBox = document.getElementById("count");
const pageInfo = document.getElementById("pageinfo");
const prevBtn = document.getElementById("prev");
const nextBtn = document.getElementById("next");

const q = document.getElementById("q");
const fStatus = document.getElementById("f-status");
const fCategory = document.getElementById("f-category");

let offset = 0;
let total = null;
let timer = null;

/* 網址帶參數，讓搜尋結果可以直接分享 / 回上一頁 */
function readUrl() {
  const params = new URLSearchParams(window.location.search);
  q.value = params.get("q") || "";
  fStatus.value = params.get("status") || "";
  fCategory.value = params.get("category") || "";
  offset = parseInt(params.get("offset") || "0", 10) || 0;
}

function writeUrl() {
  const params = new URLSearchParams();
  if (q.value) params.set("q", q.value);
  if (fStatus.value) params.set("status", fStatus.value);
  if (fCategory.value) params.set("category", fCategory.value);
  if (offset) params.set("offset", String(offset));
  const query = params.toString();
  window.history.replaceState(null, "", "/items" + (query ? "?" + query : ""));
}

function fillFilters(categories) {
  STATUSES.forEach((status) => {
    /* 選項文字翻譯，value 維持資料庫的英文值 —— 查詢參數不變。 */
    fStatus.appendChild(el("option", { value: status, text: t("status." + status) }));
  });
  /* 分類是使用者自己的資料值，原樣顯示，不翻譯。 */
  categories.forEach((category) => {
    fCategory.appendChild(el("option", { value: category, text: category }));
  });
}

function thumb(item) {
  if (!item.thumbnail) {
    return el("div", { class: "nophoto", text: t("items.no_photo") });
  }
  const image = el("img", {
    class: "thumb",
    src: photoUrl(item.thumbnail),
    alt: item.name || item.id,
    loading: "lazy",
  });
  image.addEventListener("error", () => {
    image.replaceWith(el("div", { class: "nophoto", text: t("items.no_photo") }));
  });
  return image;
}

function itemRow(item) {
  /* name / brand / model / category 全是使用者輸入的資料，原樣顯示。
     i18n 只翻「（未填名稱）」這種 UI 補的話，以及照片數量。 */
  const title = item.name || t("items.untitled");
  const bits = [];
  if (item.brand) bits.push(item.brand);
  if (item.model) bits.push(item.model);
  const rowClass = "item-row" + (item.status === "void" ? " void" : item.status === "archived" ? " archived" : "");
  return el(
    "a",
    { class: rowClass, href: "/items/" + encodeURIComponent(item.id) },
    [
      thumb(item),
      el("div", {}, [
        el("div", { class: "title", text: title }),
        el("div", { class: "meta" }, [
          el("span", { class: "id", text: item.id }),
          bits.length ? el("span", { text: bits.join(" · ") }) : null,
          item.category ? el("span", { text: item.category }) : null,
          el("span", {
            text: t("common.photo_count", { count: item.photo_count }),
          }),
          badge(item.status),
        ]),
      ]),
    ]
  );
}

async function load() {
  writeUrl();
  clear(errorBox);
  rows.setAttribute("aria-busy", "true");
  try {
    const items = await api(
      url("/api/items", {
        q: q.value,
        status: fStatus.value,
        category: fCategory.value,
        limit: PAGE_SIZE,
        offset: offset,
      })
    );
    lastLoadedItems = items;
    clear(rows);
    items.forEach((item) => rows.appendChild(itemRow(item)));

    emptyBox.hidden = items.length > 0;
    total = items.length === PAGE_SIZE ? offset + PAGE_SIZE + 1 : offset + items.length;
    countBox.textContent = t("items.range_info", {
      from: offset + 1, to: offset + items.length,
    });
    pageInfo.textContent = t("items.page_info", {
      page: Math.floor(offset / PAGE_SIZE) + 1,
    });
    prevBtn.disabled = offset === 0;
    nextBtn.disabled = items.length < PAGE_SIZE;
  } catch (err) {
    clear(rows);
    emptyBox.hidden = true;
    showError(t("items.load_failed", { message: err.message }));
    prevBtn.disabled = true;
    nextBtn.disabled = true;
  } finally {
    rows.removeAttribute("aria-busy");
  }
}

let lastLoadedItems = null;

function updateStatusFilterOptions() {
  const currentVal = fStatus.value;
  if (!fStatus.options.length) return;
  const firstOpt = fStatus.options[0];
  fStatus.replaceChildren(firstOpt);
  STATUSES.forEach((status) => {
    fStatus.appendChild(el("option", { value: status, text: t("status." + status) }));
  });
  fStatus.value = currentVal;
}

i18nSubscribe(() => {
  updateStatusFilterOptions();
  if (lastLoadedItems) {
    clear(rows);
    lastLoadedItems.forEach((item) => rows.appendChild(itemRow(item)));
    countBox.textContent = t("items.range_info", {
      from: offset + 1, to: offset + lastLoadedItems.length,
    });
    pageInfo.textContent = t("items.page_info", {
      page: Math.floor(offset / PAGE_SIZE) + 1,
    });
  }
});

/* 輸入兩個字就送出，不必等打完一整個詞 —— 兩字中文搜尋是這套工具的底線 */
function debounce(fn, delay) {
  return function () {
    clearTimeout(timer);
    timer = setTimeout(fn, delay);
  };
}

q.addEventListener("input", debounce(() => {
  offset = 0;
  load();
}, 220));

fStatus.addEventListener("change", () => { offset = 0; load(); });
fCategory.addEventListener("change", () => { offset = 0; load(); });
prevBtn.addEventListener("click", () => {
  offset = Math.max(0, offset - PAGE_SIZE);
  load();
});
nextBtn.addEventListener("click", () => {
  offset += PAGE_SIZE;
  load();
});

(async function start() {
    /* i18nInit() 必須在任何 t() 之前跑 —— 它讀 localStorage 的語言偏好
       並套用 markup 上的 data-i18n。 */
    i18nInit();
    readUrl();
    try {
    const stats = await api("/api/stats?limit=1");
    fillFilters(stats.categories || []);
  } catch (err) {
    /* 分類下拉拿不到不影響主要功能 */
  }
  load();
})();