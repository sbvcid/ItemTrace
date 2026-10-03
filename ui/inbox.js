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
let loose = null;
let selected = null;

/* 沒有時間戳的組，用 key = -1 標示。key 是數字才不會和 group.index 撞。 */
const LOOSE_KEY = -1;

function inboxPhotoUrl(relative) {
  return "/files/" + relative;
}

/* 目前可以選的所有組合：自動分組的 + 沒有時間的那批。 */
function choices() {
  return loose ? groups.concat([loose]) : groups;
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
  /* 兩種失敗必須分開講（和商品頁的 decide()／revert() 同一個道理）：
       POST 失敗 → 檔案沒進來，說「上傳失敗」，使用者可以再試
       重載失敗  → 檔案已經在 inbox 裡了，說「上傳失敗」會讓人重傳一遍，
                   inbox 就會多一份重複檔 */
  if (!files || !files.length) return;
  showError("");
  const status = document.getElementById("upload-status");
  status.hidden = false;
  status.textContent = "上傳中…（" + files.length + " 張）";
  startBtn.disabled = true;

  const body = new FormData();
  Array.from(files).forEach((file) => body.append("files", file, file.name));

  const verb = "上傳";
  try {
    await api("/api/inbox/photos", { method: "POST", body });
  } catch (err) {
    showError(verb + "失敗：" + err.message);
    startBtn.disabled = false;
    return;
  }

  status.textContent = "上傳完成";
  setTimeout(() => { status.hidden = true; }, 2000);
  try {
    await refresh();
  } catch (err) {
    showError(
      verb + "成功，但重新載入待處理清單失敗（" + err.message +
      "）。照片已經在 inbox 裡，請重新整理確認。"
    );
  } finally {
    startBtn.disabled = false;
  }
}

/* 觸發路徑只有這一條。
   #dropzone 是 div 不是 label：label 包住 file input 時點下去會由瀏覽器
   原生觸發 input，這裡再 click 一次就是雙重觸發。實機結果是 file picker
   被開兩次又立刻收掉，change 沒發，POST /api/inbox/photos 從來沒送出。 */
dropzone.addEventListener("click", (event) => {
  if (event.target !== fileInput) fileInput.click();
});
fileInput.addEventListener("change", () => {
  /* 先把 FileList 複製成 Array 再清 input —— 順序反過來會拿到 0 張。
     input.files 是「活的」FileList：把 value 設成空字串會清空 selected
     files，而 getter 在清單沒變時回傳同一個物件，所以先取參照再清空，
     那個參照會跟著變空，upload() 的 `if (!files.length) return` 就直接
     早退 —— 表面上不會報錯，實際上一張都沒上傳。
     複製成 Array 是唯一能把這批 File 固定下來的做法。 */
  const picked = Array.from(fileInput.files);
  fileInput.value = "";   // 清掉，讓同一批照片再選一次也會觸發 change
  upload(picked);
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
          el("div", {
            class: "group-time",
            text: group.captured_at ? timeRange(group) : "時間讀不出來",
          }),
        ]),
      ]),
      el("div", { class: "strip" }, first.concat(
        extra > 0 ? [el("div", { class: "cell more", text: "+" + extra })] : []
      )),
    ])
  );
  return card;
}

function selectGroup(key) {
  selected = key;
  Array.from(document.querySelectorAll(".group")).forEach((card) => {
    card.classList.toggle("on", Number(card.dataset.index) === key);
  });
  const group = choices().find((g) => g.index === key);
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

  // 沒被分到任何一組的檔案：時間解析不出來（EXIF、檔名都沒有）
  const taken = new Set(
    groups.flatMap((group) => group.entries.map((entry) => entry.relative))
  );
  const rest = entries.filter((entry) => !taken.has(entry.relative));
  loose = rest.length
    ? {
        index: LOOSE_KEY,
        captured_at: null,
        captured_from: "none",
        entries: rest,
      }
    : null;

  // 選中的組合若因為重新分組而消失，就清掉選擇
  if (selected !== null && !choices().some((g) => g.index === selected)) {
    selected = null;
    buildBox.hidden = true;
  }

  clear(groupsBox);
  groups.forEach((group) => groupsBox.appendChild(groupCard(group)));

  document.getElementById("ungrouped-sec").hidden = !loose;
  const looseBox = document.getElementById("ungrouped");
  clear(looseBox);
  if (loose) {
    document.getElementById("ungrouped-count").textContent =
      "（" + loose.entries.length + " 張）";
    // 沒有時間的那批也能建檔：走同一條 /api/inbox/intake
    looseBox.appendChild(groupCard(loose));
  }
}

gapSelect.addEventListener("change", () => {
  selected = null;
  buildBox.hidden = true;
  refresh().catch((err) => showError("分組失敗：" + err.message));
});

/* ------------------------------------------------------------ 建檔 */

startBtn.addEventListener("click", async () => {
  if (selected === null) return;
  const group = choices().find((g) => g.index === selected);
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