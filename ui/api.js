/* 與後端共用的小工具：只有 fetch 與 DOM 組裝，沒有框架也沒有建置。 */

const API = "";

function url(path, params) {
  const target = new URL(API + path, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      target.searchParams.set(key, value);
    }
  });
  return target.toString();
}

async function api(path, options) {
  const response = await fetch(API + path, options);
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

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  });
  (children || []).forEach((child) => {
    if (child === null || child === undefined) return;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  });
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function showError(message) {
  const box = document.getElementById("error");
  clear(box);
  if (message) box.appendChild(el("div", { class: "error", text: message }));
}

function photoUrl(filename) {
  return API + "/files/" + filename;
}

/* 照片載入失敗時的替代畫面：原始照片不可破壞，所以不能假裝不存在。 */
function photoNode(photo, caption) {
  const figure = el("figure");
  const image = el("img", {
    src: photoUrl(photo.filename),
    alt: caption || photo.orig_name || t("item.photo_alt"),
    loading: "lazy",
  });
  image.addEventListener("error", () => {
    figure.replaceChildren(
      el("div", {
        class: "broken",
        text: t("common.unreadable", {
          filename: photo.orig_name || photo.filename,
        }),
      })
    );
  });
  figure.appendChild(image);
  if (caption) figure.appendChild(el("figcaption", { text: caption }));
  return figure;
}

/* 歸檔生命週期的 badge。status 是 API 的原始值（active / archived /
   void），className 與篩選條件都用原始值，只有顯示文字走翻譯 ——
   class 名不能翻譯，CSS 與測試都靠它。
   未知值（例如日後加了新的 status）原樣顯示：這比顯示錯誤的翻譯好，
   而且一眼看得出資料層加了值但這裡還沒翻。 */
function badge(status) {
  const label = Object.prototype.hasOwnProperty.call(
    { active: 1, archived: 1, void: 1 }, status
  ) ? t("status." + status) : status;
  return el("span", { class: "badge " + status, text: label });
}

function shortTime(iso) {
  if (!iso) return "";
  return iso.replace("T", " ").slice(0, 16);
}