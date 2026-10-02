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
    fStatus.appendChild(el("option", { value: status, text: status }));
  });
  categories.forEach((category) => {
    fCategory.appendChild(el("option", { value: category, text: category }));
  });
}

function thumb(item) {
  if (!item.thumbnail) {
    return el("div", { class: "nophoto", text: "無照片" });
  }
  const image = el("img", {
    class: "thumb",
    src: photoUrl(item.thumbnail),
    alt: item.name || item.id,
    loading: "lazy",
  });
  image.addEventListener("error", () => {
    image.replaceWith(el("div", { class: "nophoto", text: "無照片" }));
  });
  return image;
}

function itemRow(item) {
  const title = item.name || "（未填品名）";
  const bits = [];
  if (item.brand) bits.push(item.brand);
  if (item.model) bits.push(item.model);
  return el(
    "a",
    { class: "item-row", href: "/items/" + encodeURIComponent(item.id) },
    [
      thumb(item),
      el("div", {}, [
        el("div", { class: "title", text: title }),
        el("div", { class: "meta" }, [
          el("span", { class: "id", text: item.id }),
          bits.length ? el("span", { text: bits.join(" · ") }) : null,
          item.category ? el("span", { text: item.category }) : null,
          el("span", { text: item.photo_count + " 張照片" }),
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
    clear(rows);
    items.forEach((item) => rows.appendChild(itemRow(item)));

    emptyBox.hidden = items.length > 0;
    total = items.length === PAGE_SIZE ? offset + PAGE_SIZE + 1 : offset + items.length;
    countBox.textContent = "第 " + (offset + 1) + "–" + (offset + items.length) + " 筆";
    pageInfo.textContent = "第 " + (Math.floor(offset / PAGE_SIZE) + 1) + " 頁";
    prevBtn.disabled = offset === 0;
    nextBtn.disabled = items.length < PAGE_SIZE;
  } catch (err) {
    clear(rows);
    emptyBox.hidden = true;
    showError("讀取失敗：" + err.message);
    prevBtn.disabled = true;
    nextBtn.disabled = true;
  } finally {
    rows.removeAttribute("aria-busy");
  }
}

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
  readUrl();
  try {
    const stats = await api("/api/stats?limit=1");
    fillFilters(stats.categories || []);
  } catch (err) {
    /* 分類下拉拿不到不影響主要功能 */
  }
  load();
})();