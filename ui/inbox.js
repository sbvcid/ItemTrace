/* Inbox：上傳 → 依拍攝時間分組 → 選一組 → 一鍵建檔。

  分組完全交給後端（POST /api/inbox/group），前端不自己讀 EXIF；
  搬檔與建檔也交給後端（POST /api/inbox/intake），前端不上傳已存在的檔案。
*/

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const groupsBox = document.getElementById("groups");
const buildBox = document.getElementById("build");
const startBtn = document.getElementById("start");
const gapSelect = document.getElementById("gap");
const errorBox = document.getElementById("error");

let entries = [];
let groups = [];
let selected = null;

function inboxPhotoUrl(relative) {
  return "/files/" + relative;
}

/* ------------------------------------------------------------ 縮圖 */

function thumb(relative, caption) {
  const figure = el("figure", { class: "cell" });
  const image = el("img", {
    src: inboxPhotoUrl(relative),
    alt: caption || relative,
    loading: "lazy",
  });
  image.addEventListener("error", () => {
    figure.replaceChildren(el("div", { class: "broken", text: "讀不到" }));
  });
  figure.appendChild(image);
  if (caption) figure.appendChild(el("figcaption", { text: caption }));
  return figure;
}

/* ------------------------------------------------------------ 上傳 */

async function upload(files) {
  if (!files || !files.length) return;
  showError("");
  const status = document.getElementById("upload-status");
  status.hidden = false;
  status.textContent = "上傳中…（" + files.length + " 張）";
  startBtn.disabled = true;

  const body = new FormData();
  Array.from(files).forEach((file) => body.append("files", file, file.name));

  try {
    await api("/api/inbox/photos", { method: "POST", body });
    status.textContent = "上傳完成";
    setTimeout(() => { status.hidden = true; }, 2000);
    await refresh();
  } catch (err) {
    showError("上傳失敗：" + err.message);
  } finally {
    startBtn.disabled = false;
  }
}

dropzone.addEventListener("click", (event) => {
  if (event.target !== fileInput) fileInput.click();
});
fileInput.addEventListener("change", () => {
  upload(fileInput.files);
  fileInput.value = "";
});

/* 桌機拖放；手機上 click 才是主要入口 */
["dragenter", "dragover"].forEach((name) => {
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("over");
  });
});
["dragleave", "drop"].forEach((name) => {
  dropzone.addEventListener(name, () => dropzone.classList.remove("over"));
});
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  upload(event.dataTransfer.files);
});

/* ------------------------------------------------------------ 分組 */

function timeRange(group) {
  const times = group.entries
    .map((entry) => entry.captured_at)
    .filter(Boolean)
    .sort();
  if (!times.length) return "";
  const day = (iso) => iso.slice(5, 10).replace("-", "/");
  const hm = (iso) => iso.slice(11, 16);
  if (day(times[0]) !== day(times[times.length - 1])) {
    return day(times[0]) + " " + hm(times[0]) + " → " +
           day(times[times.length - 1]) + " " + hm(times[times.length - 1]);
  }
  return day(times[0]) + " " + hm(times[0]) + " – " + hm(times[times.length - 1]);
}

function groupCard(group) {
  const card = el("label", { class: "group", "data-index": group.index });
  const first = group.entries.slice(0, 5).map((entry) =>
    thumb(entry.relative, entry.captured_at ? entry.captured_at.slice(11, 16) : "")
  );
  const extra = group.entries.length - first.length;

  card.appendChild(
    el("div", {}, [
      el("div", { class: "group-line" }, [
        el("input", {
          type: "radio",
          name: "group",
          value: String(group.index),
          onchange: () => selectGroup(group.index),
        }),
        el("div", { class: "grow" }, [
          el("div", { class: "group-count", text: group.entries.length + " 張照片" }),
          el("div", { class: "group-time", text: timeRange(group) }),
        ]),
      ]),
      el("div", { class: "strip" }, first.concat(
        extra > 0 ? [el("div", { class: "cell more", text: "+" + extra })] : []
      )),
    ])
  );
  return card;
}

function selectGroup(index) {
  selected = index;
  Array.from(groupsBox.querySelectorAll(".group")).forEach((card) => {
    card.classList.toggle("on", Number(card.dataset.index) === index);
  });
  const group = groups.find((g) => g.index === index);
  document.getElementById("build-label").textContent =
    "已選 " + group.entries.length + " 張，開始建檔？";
  buildBox.hidden = false;
  startBtn.focus();
}

/* --------------------------------------------------- 讀取與渲染 */

async function refresh() {
  showError("");
  const [listing, grouped] = await Promise.all([
    api("/api/inbox"),
    api(url("/api/inbox/group", { gap_minutes: gapSelect.value }), { method: "POST" }),
  ]);

  entries = listing.entries;
  groups = grouped;

  document.getElementById("count").textContent =
    entries.length ? entries.length + " 張待處理" : "";
  document.getElementById("nothing").hidden = entries.length > 0;
  document.getElementById("groups-sec").hidden = groups.length === 0;

  // 選中的組若因為重新分組而消失，就清掉選擇
  if (selected !== null && !groups.some((g) => g.index === selected)) {
    selected = null;
    buildBox.hidden = true;
  }

  clear(groupsBox);
  groups.forEach((group) => groupsBox.appendChild(groupCard(group)));

  // 沒被分到任何一組的檔案：通常是時間解析不出來
  const taken = new Set(
    groups.flatMap((group) => group.entries.map((entry) => entry.relative))
  );
  const loose = entries.filter((entry) => !taken.has(entry.relative));
  document.getElementById("ungrouped-wrap").hidden = loose.length === 0;
  document.getElementById("ungrouped-count").textContent =
    loose.length ? "（" + loose.length + " 張）" : "";
  const strip = document.getElementById("ungrouped");
  clear(strip);
  loose.forEach((entry) => strip.appendChild(thumb(entry.relative, entry.captured_at
    ? entry.captured_at.slice(11, 16)
    : "無時間")));
}

gapSelect.addEventListener("change", () => {
  selected = null;
  buildBox.hidden = true;
  refresh().catch((err) => showError("分組失敗：" + err.message));
});

/* ------------------------------------------------------------ 建檔 */

startBtn.addEventListener("click", async () => {
  if (selected === null) return;
  const group = groups.find((g) => g.index === selected);
  if (!group || !group.entries.length) return;

  startBtn.disabled = true;
  startBtn.textContent = "建檔中…";
  showError("");
  try {
    const done = await api("/api/inbox/intake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        files: group.entries.map((entry) => entry.relative),
        kind: "intake",
      }),
    });
    if (done.item_id) {
      // 直接導向商品詳細頁 —— 照片已經在那裡了
      window.location.href = "/items/" + encodeURIComponent(done.item_id);
      return;
    }
    // 全部都是重複匯入，沒有新商品可去
    startBtn.textContent = "開始建檔";
    await refresh();
  } catch (err) {
    showError("建檔失敗（資料沒有半套）：" + err.message);
  } finally {
    startBtn.disabled = false;
    if (startBtn.textContent === "建檔中…") startBtn.textContent = "開始建檔";
  }
});

refresh().catch((err) => showError("讀取失敗：" + err.message));