/* 商品詳細頁：照片優先。欄位編輯只走既有 PATCH，沒有 inline editor。 */

const ITEM_ID = decodeURIComponent(window.location.pathname.split("/").pop() || "");

const FIELDS = [
  "name", "brand", "model", "category", "quantity", "condition", "notes",
];

const detail = document.getElementById("detail");
const notFound = document.getElementById("notfound");
const wall = document.getElementById("wall");
const saved = document.getElementById("saved");

let current = null;
let dirty = new Set();

function field(id) {
  return document.getElementById("f-" + id);
}

/* ---------------------------------------------------------------- 照片牆 */

function renderWall(photos) {
  clear(wall);
  document.getElementById("wall-empty").hidden = photos.length > 0;
  document.getElementById("wall-count").textContent =
    photos.length ? "（" + photos.length + " 張）" : "";

  photos.forEach((photo) => {
    const caption = [
      photo.orig_name,
      photo.angle ? "［" + photo.angle + "］" : "",
      photo.captured_at ? photo.captured_at.slice(0, 16).replace("T", " ") : "",
    ].filter(Boolean).join(" ");

    const figure = photoNode(photo, caption);
    // 點照片看原尺寸；原始照片只能看，不能在這裡刪
    figure.style.cursor = "zoom-in";
    figure.addEventListener("click", () => {
      window.open(photoUrl(photo.filename), "_blank", "noopener");
    });
    wall.appendChild(figure);
  });
}

/* ------------------------------------------------------------ 建議 */

/* field 是 API 的欄位名，顯示給人看的用中文。 */
const FIELD_LABELS = {
  name: "品名",
  brand: "品牌",
  model: "型號",
  category: "分類",
  condition: "品況",
  notes: "備註",
};

const IDENTIFIER_LABELS = {
  serial: "序號",
  imei: "IMEI",
  barcode: "條碼",
  custom: "識別碼",
};

function fieldLabel(field) {
  if (isIdentifierField(field)) {
    const kind = field.slice("identifier:".length);
    return IDENTIFIER_LABELS[kind] || "識別碼";
  }
  return FIELD_LABELS[field] || field;
}

/* 注意：identifier_kind 是 Python dataclass 的 property，API 回應裡沒有這個
   key，所以這裡要從 field 字串自己判斷。 */
function isIdentifierField(field) {
  return String(field).indexOf("identifier:") === 0;
}

/* SPEC-v1 §6：建議值與識別碼旁要顯示「來源照片縮圖」。縮圖直接用 original
   檔（derived/ 在 v1 沒有縮圖產生器），靠 object-fit 裁成小方塊。
   用 <a> 而不是 <button>：原生開新分頁、可 middle-click、鍵盤可用，
   也不需要 onclick。沒有來源照片就明講，不顯示死掉的圖。 */
function sourceThumb(photo, caption) {
  const label = caption || photo.orig_name || "來源照片";
  const link = el("a", {
    class: "thumb",
    "data-role": "source-thumb",
    href: photoUrl(photo.filename),
    target: "_blank",
    rel: "noopener",
    title: label,
  });
  const image = el("img", { src: photoUrl(photo.filename), alt: label, loading: "lazy" });
  image.addEventListener("error", () => {
    link.replaceChildren(el("span", { class: "thumb-fail", text: "讀不到" }));
  });
  link.appendChild(image);
  return link;
}

function suggestionCard(suggestion, photosById) {
  const source = suggestion.source_photo_id
    ? photosById.get(suggestion.source_photo_id)
    : null;
  const meta = [
    suggestion.confidence !== null ? "信心 " + suggestion.confidence : "",
    suggestion.model_name ? suggestion.model_name : "",
  ].filter(Boolean);

  const errorSlot = el("div", { class: "sugg-error", hidden: true });
  const card = el("div", { class: "sugg", "data-suggestion": suggestion.id }, [
    source ? sourceThumb(source) : null,
    el("div", { class: "sugg-main" }, [
      el("div", { class: "sugg-line" }, [
        el("span", { class: "badge", text: fieldLabel(suggestion.field) }),
        el("span", { class: "sugg-value", text: suggestion.value }),
      ]),
      meta.length
        ? el("div", { class: "dim", style: "font-size:12.5px", text: meta.join(" · ") })
        : null,
      el("div", { class: "sugg-foot" }, [
        source
          ? el("a", {
              href: photoUrl(source.filename),
              target: "_blank",
              rel: "noopener",
              text: "看來源照片",
            })
          : el("span", { class: "dim", text: "沒有來源照片" }),
        suggestion.identifier_kind || isIdentifierField(suggestion.field)
          ? el("span", { class: "dim", style: "font-size:12px", text: "接受後會建立識別碼" })
          : null,
        el("span", { style: "flex:1" }),
        decisionButton(suggestion, "reject", "拒絕"),
        decisionButton(suggestion, "accept", "接受"),
      ]),
    ]),
    errorSlot,
  ]);
  card.errorSlot = errorSlot;
  return card;
}

function decisionButton(suggestion, action, label) {
  return el("button", {
    class: action === "accept" ? "primary" : "",
    "data-action": action,
    "data-id": suggestion.id,
    text: label,
    onclick: () => decide(cardFor(suggestion.id), suggestion.id, action),
  });
}

function cardFor(suggestionId) {
  return document.querySelector('.sugg[data-suggestion="' + suggestionId + '"]');
}

/* 接受或拒絕。
   兩種失敗必須分開講：
     POST 失敗      → 伺服器沒動，建議仍是 pending → 卡片留著、按鈕交回去
     重載失敗       → 建議已經被接受了，只是畫面過期
   混在一起會出兩種毛病：該再按一次的人按不到，不該再按的人一直按到 400。 */
async function decide(card, suggestionId, action) {
  const slot = card.errorSlot;
  slot.hidden = true;
  slot.textContent = "";
  setCardBusy(card, true);

  const verb = action === "accept" ? "接受" : "拒絕";
  try {
    await api(
      "/api/suggestions/" + encodeURIComponent(suggestionId) + "/" + action,
      { method: "POST" }
    );
  } catch (err) {
    /* 伺服器沒動 → 建議仍是 pending，把按鈕交回去讓人再試一次 */
    setCardBusy(card, false);
    slot.hidden = false;
    slot.textContent = verb + "失敗：" + err.message;
    return;
  }

  /* 到這裡建議已經被決定了，接下來重載失敗也不能說「接受失敗」 */
  try {
    await refresh();
  } catch (err) {
    /* 訊息放在頁面層級的提示區，不放在那張卡上 ——
       refresh() 可能已經換掉卡片，寫進被移除的節點等於沒寫。
       提示區在 .wrap 頂端、不受 render 影響，而且會捲進視線。 */
    showError(
      verb + "成功，但重新載入資料失敗（" + err.message +
      "）。畫面可能不是最新的，請重新整理確認結果。"
    );
    const box = document.getElementById("error");
    if (box && typeof box.scrollIntoView === "function") {
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

function setCardBusy(card, busy) {
  card.querySelectorAll("button").forEach((button) => { button.disabled = busy; });
}

function renderSuggestions(items, photosById) {
  const pending = items.filter((item) => item.status === "pending");
  const decided = items.length - pending.length;

  document.getElementById("pending-sec").hidden = pending.length === 0;
  document.getElementById("pending-count").textContent = pending.length
    ? "（" + pending.length + " 筆待確認" +
      (decided ? "，已決定 " + decided + " 筆" : "") + "）"
    : "";

  const box = document.getElementById("pending");
  clear(box);
  pending.forEach((item) => box.appendChild(suggestionCard(item, photosById)));
}

/* ------------------------------------------------------------ 識別碼 */

async function renderIdentifiers(identifiers, photosById) {
  const body = document.querySelector("#identifiers tbody");
  clear(body);
  document.getElementById("id-empty").hidden = identifiers.length > 0;

  // 撞號檢查用既有 lookup 端點：正規化後完全相同、但屬於別的商品。
  // 查不到就不顯示，不自己發明 API。
  const collisions = new Map();
  await Promise.all(
    identifiers.map(async (identifier) => {
      try {
        const found = await api(
          url("/api/identifiers/lookup", { value: identifier.normalized })
        );
        const others = (found.matches || []).filter(
          (row) =>
            row.item_id !== identifier.item_id &&
            row.normalized === identifier.normalized
        );
        if (others.length) collisions.set(identifier.id, others);
      } catch (err) {
        /* 查不到就當沒有撞號 */
      }
    })
  );

  identifiers.forEach((identifier) => {
    const conflict = collisions.get(identifier.id);
    const source = photosById.get(identifier.source_photo_id);
    body.appendChild(
      el("tr", {}, [
        el("td", {}, [
          el("span", { class: "badge", text: identifier.kind }),
        ]),
        el("td", {}, [
          el("div", { class: "ident-value" }, [
            /* SPEC §6：識別碼欄位旁永遠顯示來源照片縮圖 */
            source ? sourceThumb(source) : null,
            el("div", {}, [
              el("div", { text: identifier.value }),
              identifier.confidence !== null
                ? el("div", { class: "dim", style: "font-size:12px" }, [
                    "信心 " + identifier.confidence +
                      (identifier.source === "accepted_suggestion" ? " · 來自建議" : ""),
                  ])
                : null,
            ]),
          ]),
          conflict
            ? el("div", { class: "badge warn", style: "margin-top:6px" },
                conflict.map((row) =>
                  /* SPEC §6：撞號提示附既有 item 的連結供比對。
                     item_id 就在 lookup 的回應裡，不用另外開端點。 */
                  el("span", { style: "margin-right:8px" }, [
                    "⚠ 撞號：",
                    el("a", {
                      href: "/items/" + encodeURIComponent(row.item_id),
                      "data-collision-link": row.item_id,
                      text: row.item_id,
                    }),
                    " 也有相同識別碼",
                  ])
                )
              )
            : null,
        ]),
        el("td", {}, [
          source
            ? el("a", {
                href: photoUrl(source.filename),
                target: "_blank",
                rel: "noopener",
                text: "看來源照片",
              })
            : el("span", { class: "dim", text: "—" }),
        ]),
      ])
    );
  });
}

/* -------------------------------------------------------------- 觀測 */

function renderObservations(observations, photosById) {
  const body = document.querySelector("#observations tbody");
  clear(body);
  document.getElementById("obs-empty").hidden = observations.length > 0;

  observations.forEach((observation) => {
    const photos = observation.photos || [];
    body.appendChild(
      el("tr", {}, [
        el("td", { class: "id", text: observation.id }),
        el("td", {}, [el("span", { class: "badge", text: observation.kind })]),
        el("td", {}, [
          el("div", { text: shortTime(observation.captured_at || observation.created_at) }),
          observation.note
            ? el("div", { class: "dim", style: "font-size:12.5px", text: observation.note })
            : null,
        ]),
        el("td", {}, [
          photos.length
            ? el("a", {
                href: photoUrl(photos[0].filename),
                target: "_blank",
                rel: "noopener",
                text: photos.length + " 張",
              })
            : el("span", { class: "dim", text: "—" }),
        ]),
      ])
    );
  });
}

/* -------------------------------------------------------------- 歷史 */

/* 可復原的範圍。

   backend 的 Repository.revert_event() 是權威契約：除了 type='field.changed'、
   field 與 prev_value 都要在，它還會檢查 entity_type 有沒有在 _REVERT_TARGETS，
   以及 field 有沒有在該 entity 的可改欄位裡。所以只照前三項判斷會出現
   「按鈕看得到、按下去必定 400」。

   把整份 _REVERT_TARGETS 複製過來只是換一份會漂移的規則，這裡只列商品頁
   真正需要的兩個 entity：

     item        這一頁的表單就在改這些欄位，是復原的主要用途。
                 attributes / status 不在表單裡，但後端允許復原，所以一併列入
                 （用 FIELDS 串出來，避免兩份欄位清單各自漂移）。
     identifier  序號打錯要救得回來，value 是最常見的。
                 注意 backend 不允許復原 'normalized'：update_identifier 會為
                 它寫 field.changed，但它不在 IDENTIFIER_EDITABLE_FIELDS 裡，
                 所以不能列。

   刻意排除（測試會驗證這些事件確實沒有按鈕）：
     observation / photo  商品頁沒有這兩者的編輯入口，這些 field.changed 只
                          可能來自直接呼叫 API。
     suggestion          商品頁不能編輯建議；而已決定的建議在 backend 的
                          update_suggestion() 會直接擲錯，本來就不可復原。 */
const REVERTIBLE = {
  item: FIELDS.concat(["attributes", "status"]),
  identifier: ["value", "kind", "confidence", "source", "source_photo_id"],
};

function canRevert(event) {
  const allowed = REVERTIBLE[event.entity_type];
  return !!allowed &&
         event.type === "field.changed" &&
         allowed.indexOf(event.field) !== -1 &&
         event.prev_value !== null;
}

function revertButton(event) {
  return el("button", {
    "data-action": "revert",
    "data-id": event.id,
    text: "復原",
    onclick: () => revert(rowFor(event.id), event.id),
  });
}

function rowFor(eventId) {
  return document.querySelector('.event[data-event="' + eventId + '"]');
}

function eventRow(event) {
  const what = el("div", { class: "what" }, [
    el("b", { text: event.type }),
    event.field ? " · " + fieldLabel(event.field) : "",
  ]);
  if (event.prev_value !== null || event.next_value !== null) {
    what.appendChild(
      el("div", { class: "val" }, [
        JSON.stringify(event.prev_value),
        " → ",
        el("span", { class: "to", text: JSON.stringify(event.next_value) }),
      ])
    );
  }

  const errorSlot = el("div", { class: "event-error", hidden: true });
  const row = el("div", { class: "event", "data-event": event.id }, [
    el("div", { class: "when", text: shortTime(event.created_at) }),
    el("div", { class: "event-body" }, [
      what,
      el("div", { class: "dim", style: "font-size:12px" }, [
        [event.actor, event.entity_type].filter(Boolean).join(" · "),
      ]),
    ]),
    canRevert(event) ? el("div", { class: "event-act" }, [revertButton(event)]) : null,
    errorSlot,
  ]);
  row.errorSlot = errorSlot;
  return row;
}

/* 復原是「對單一事件做反向操作」，不是回到某個時間點。
   後端會把 prev_value 寫回並另記一筆 field.changed，原事件不動 ——
   所以 A → B → 復原 會得到 A → B → A 的完整事件鏈。 */
async function revert(row, eventId) {
  const slot = row.errorSlot;
  slot.hidden = true;
  slot.textContent = "";
  setRowBusy(row, true);

  try {
    await api("/api/events/" + encodeURIComponent(eventId) + "/revert",
              { method: "POST" });
  } catch (err) {
    /* 伺服器沒動 → 歷史沒變，按鈕交回去讓人再試一次 */
    setRowBusy(row, false);
    slot.hidden = false;
    slot.textContent = "復原失敗：" + err.message;
    return;
  }

  /* 復原已經發生了。重載失敗不能說「復原失敗」，那會讓人再按一次。 */
  try {
    await refresh();
  } catch (err) {
    /* 訊息放頁面層級：refresh 可能已經把這列換掉，寫進舊節點等於沒寫。
       按鈕維持鎖住 —— 別再對同一個事件按第二次。 */
    showError(
      "復原成功，但重新載入資料失敗（" + err.message +
      "）。畫面可能不是最新的，請重新整理確認結果。"
    );
    const box = document.getElementById("error");
    if (box && typeof box.scrollIntoView === "function") {
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

function setRowBusy(row, busy) {
  row.querySelectorAll("button").forEach((button) => { button.disabled = busy; });
}

function renderEvents(events) {
  const box = document.getElementById("events");
  clear(box);
  document.getElementById("event-count").textContent = String(events.length);
  if (!events.length) {
    box.appendChild(el("div", { class: "dim", text: "沒有紀錄" }));
    return;
  }
  events.forEach((event) => box.appendChild(eventRow(event)));
}

/* -------------------------------------------------------------- 編輯 */

function fillForm(item, keepDirty) {
  FIELDS.forEach((name) => {
    /* 使用者可能正在這個欄位打字 —— 重載資料時不能蓋掉還沒存檔的內容 */
    if (keepDirty && dirty.has(name)) return;
    field(name).value = item[name] === null ? "" : item[name];
  });
  if (!keepDirty) dirty = new Set();
}

async function save(event) {
  event.preventDefault();
  showError("");
  const changes = {};
  FIELDS.forEach((name) => {
    if (!dirty.has(name)) return;
    let value = field(name).value;
    if (name === "quantity") value = value === "" ? 1 : parseInt(value, 10);
    changes[name] = value;
  });
  if (!Object.keys(changes).length) return;

  const button = document.getElementById("save");
  button.disabled = true;
  let updated;
  try {
    updated = await api("/api/items/" + encodeURIComponent(current.id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
  } catch (err) {
    /* PATCH 沒成功 → 資料沒動，說「儲存失敗」是對的 */
    showError("儲存失敗：" + err.message);
    button.disabled = false;
    return;
  }

  /* 到這裡欄位已經改成功了。接著只是把歷史拉回來，
     就算拉不到也不能說「儲存失敗」 —— 那會讓人以為要再存一次。 */
  current = updated;
  FIELDS.forEach((name) => { field(name).value = updated[name]; });
  dirty = new Set();
  document.getElementById("head-status").replaceChildren(badge(updated.status));
  document.getElementById("updated").textContent =
    "更新於 " + shortTime(updated.updated_at);
  saved.hidden = false;
  saved.textContent = "已儲存";
  setTimeout(() => { saved.hidden = true; }, 2000);
  button.disabled = false;

  try {
    renderEvents(await api("/api/items/" + encodeURIComponent(current.id) + "/events"));
  } catch (err) {
    showError("欄位已儲存，但修改歷史載入失敗（" + err.message + "）。");
  }
}

async function loadCategories() {
  try {
    const stats = await api("/api/stats?limit=1");
    const box = document.getElementById("cats");
    clear(box);
    (stats.categories || []).forEach((category) => {
      box.appendChild(el("option", { value: category }));
    });
  } catch (err) {
    /* 只是 autocomplete，拿不到就算了 */
  }
}

document.getElementById("form").addEventListener("submit", save);
FIELDS.forEach((name) => {
  field(name).addEventListener("input", () => dirty.add(name));
});

async function refresh() {
  /* 資料先全部拿到手，再動畫面。
     先渲染建議卡片、才去抓 events 的話，events 失敗會留下半套畫面：
     卡片已被換掉、欄位還是舊的，錯誤訊息又被寫進一個已經從 DOM 移除的
     節點裡，使用者什麼都看不到。 */
  const [data, events] = await Promise.all([
    api("/api/items/" + encodeURIComponent(ITEM_ID)),
    api("/api/items/" + encodeURIComponent(ITEM_ID) + "/events"),
  ]);

  current = data.item;
  detail.hidden = false;

  document.getElementById("head-id").textContent = current.id;
  document.getElementById("head-status").replaceChildren(badge(current.status));
  document.getElementById("updated").textContent =
    "更新於 " + shortTime(current.updated_at);

  /* 接受建議後會重載資料，但不要蓋掉還沒存檔的輸入 ——
     使用者可能正在備註欄打字，順手點了接受，內容不能就這樣消失。
     沒動過的欄位照常更新，所以接受的品牌還是會立刻顯示出來。 */
  fillForm(current, true);
  renderWall(data.photos);

  const photosById = new Map(data.photos.map((photo) => [photo.id, photo]));
  const byObservation = {};
  data.photos.forEach((photo) => {
    if (!photo.observation_id) return;
    (byObservation[photo.observation_id] =
      byObservation[photo.observation_id] || []).push(photo);
  });

  renderSuggestions(data.suggestions || [], photosById);
  await renderIdentifiers(data.identifiers || [], photosById);
  renderObservations(
    (data.observations || []).map((observation) => ({
      ...observation,
      photos: byObservation[observation.id] || [],
    })),
    photosById
  );
  renderEvents(events);
  loadCategories();
}

(async function start() {
  showError("");
  try {
    await refresh();
  } catch (err) {
    notFound.hidden = false;
    showError(err.message);
  }
})();