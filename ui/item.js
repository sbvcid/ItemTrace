/* 商品詳細頁：照片優先。欄位編輯只走既有 PATCH，沒有 inline editor。 */

const ITEM_ID = decodeURIComponent(window.location.pathname.split("/").pop() || "");

const FIELDS = [
  "name", "brand", "model", "category", "quantity", "condition", "notes",
];

const detail = document.getElementById("detail");
const notFound = document.getElementById("notfound");
const wall = document.getElementById("wall");
const saved = document.getElementById("saved");
const aiButton = document.getElementById("ai-analyze");
const aiStatus = document.getElementById("ai-status");

let current = null;
let dirty = new Set();
let lastItemData = null;
let lastEventsData = null;

function field(id) {
  return document.getElementById("f-" + id);
}

/* ---------------------------------------------------------------- 照片牆 */

function renderWall(photos) {
  clear(wall);
  document.getElementById("wall-empty").hidden = photos.length > 0;
  document.getElementById("wall-count").textContent =
    photos.length ? t("item.photo_count_suffix", { count: photos.length }) : "";

  photos.forEach((photo) => {
    /* caption 是照片的中繼資料（檔名、角度、時間），不是 UI 文案 ——
       所以除了包裝用的括號以外，值一律原樣顯示，不翻譯。 */
    const caption = [
      photo.orig_name,
      photo.angle ? t("item.angle_bracket", { angle: photo.angle }) : "",
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

/* 這張表在 3C／二手語意改成通用物品語意時被改過一次：label 從
 * 「型號／分類／品況」換成「規格／型號／類型／狀態」。寫下來是為了讓
 * 日後改回去的人知道為什麼要這樣改，也避免有人以為那幾個字是舊的雜訊。
 *
 * field → 翻譯 key 的對照。
 *
 * 這裡的 key 是內部欄位名（資料庫與 API 的契約，不可改），value 是
 * i18n key。兩者是不同層的東西，中間這張表就是它們唯一的橋樑 ——
 * 不要把 key 改成中文，也不要在別處再寫一份中文對照。
 *
 * 語意說明（為什麼是這些 label）：
 *   - `model` 顯示成「規格／型號」而不是「型號」，因為這一欄要能裝
 *     尺寸、容量、版本、SKU，不只電子產品型號。
 *   - `condition` 顯示成「狀態」，因為物品的狀態描述取決於領域。
 *   - `status`（items.status）是歸檔生命週期，不是商品欄位。它會出現在
 *     修改歷史裡，所以也要有 label —— 而且必須跟 condition 的「狀態」
 *     區開，否則歷史會出現兩個都叫「狀態」的東西。
 *   - `attributes` / `quantity` 不在表單裡，但事件會帶 field 名，
 *     沒有 label 就會直接把內部英文名露給使用者。 */
const FIELD_LABEL_KEYS = {
  name: "item.name_label",
  brand: "item.brand_label",
  model: "item.model_label",
  category: "item.category_label",
  condition: "item.condition_label",
  notes: "item.notes_label",
  status: "item.item_status_label",
  attributes: "item.attributes_label",
  quantity: "item.quantity_label",
};

/* 識別碼種類 → 翻譯 key。unknown fallback 用 identifier.title。 */
const IDENTIFIER_LABEL_KEYS = {
  serial: "identifier.kind.serial",
  imei: "identifier.kind.imei",
  barcode: "identifier.kind.barcode",
  custom: "identifier.kind.custom",
};

/* 觀測種類（shop/ids.py 的 OBSERVATION_KINDS）。
   這些值會直接顯示成 badge，所以要翻譯；但資料庫裡存的值不變。 */
const OBSERVATION_KIND_KEYS = {
  intake: "observation.kind.intake",
  recheck: "observation.kind.recheck",
  manual: "observation.kind.manual",
};

/* 修改歷史的 event.type（shop/events.py 與 shop/repo.py 會寫進來的
   封閉清單）。值本身是資料，不該翻；但顯示出來給人看的字是 UI，該翻。 */
const EVENT_TYPE_KEYS = {
  "item.created": "event.type.item_created",
  "field.changed": "event.type.field_changed",
  "observation.created": "event.type.observation_created",
  "photo.created": "event.type.photo_created",
  "photo.deleted": "event.type.photo_deleted",
  "identifier.created": "event.type.identifier_created",
  "identifier.deleted": "event.type.identifier_deleted",
  "suggestion.created": "event.type.suggestion_created",
  "suggestion.accepted": "event.type.suggestion_accepted",
  "suggestion.rejected": "event.type.suggestion_rejected",
  "template.created": "event.type.template_created",
  "template.updated": "event.type.template_updated",
  "template.deleted": "event.type.template_deleted",
};

const EVENT_ACTOR_KEYS = {
  user: "event.actor.user",
  external: "event.actor.external",
  system: "event.actor.system",
};

const EVENT_ENTITY_KEYS = {
  item: "event.entity.item",
  identifier: "event.entity.identifier",
  photo: "event.entity.photo",
  observation: "event.entity.observation",
  suggestion: "event.entity.suggestion",
  template: "event.entity.template",
};

/* 封閉清單的值 → 顯示文字。表裡沒有的值（例如舊資料或日後新增的種類）
   原樣顯示：顯示一個看得懂的原始值，比顯示錯誤的翻譯好，而且看得出來
   資料層加了值但這裡還沒補翻譯。 */
function enumLabel(table, value) {
  if (value === undefined || value === null || value === "") return "";
  return Object.prototype.hasOwnProperty.call(table, value)
    ? t(table[value])
    : value;
}

function fieldLabel(field) {
  if (isIdentifierField(field)) {
    const kind = field.slice("identifier:".length);
    return t(IDENTIFIER_LABEL_KEYS[kind] || "identifier.kind.custom");
  }
  /* 沒有對應 key 就退回欄位名本身：顯示 "foo" 比顯示空白好，
     而且看得出來是漏了翻譯而不是資料壞掉。 */
  return t(FIELD_LABEL_KEYS[field] || field);
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
  const label = caption || photo.orig_name || t("common.source_photo_alt");
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
    link.replaceChildren(el("span", {
      class: "thumb-fail", text: t("common.unreadable_short"),
    }));
  });
  link.appendChild(image);
  return link;
}

function suggestionCard(suggestion, photosById) {
  const source = suggestion.source_photo_id
    ? photosById.get(suggestion.source_photo_id)
    : null;
  /* model_name 是 AI 服務回報的模型名稱，不是 UI 文案 —— 原樣顯示。
     翻譯的是「信心」這個詞。 */
  const meta = [
    suggestion.confidence !== null
      ? t("identifier.confidence", { value: suggestion.confidence }) : "",
    suggestion.model_name ? suggestion.model_name : "",
  ].filter(Boolean);

  const errorSlot = el("div", { class: "sugg-error", hidden: true });
  const card = el("div", { class: "sugg", "data-suggestion": suggestion.id }, [
    source ? sourceThumb(source) : null,
    el("div", { class: "sugg-main" }, [
      el("div", { class: "sugg-line" }, [
        el("span", { class: "badge", text: fieldLabel(suggestion.field) }),
        /* suggestion.value 是 AI 從照片推出來的「值」—— 是資料不是 UI，
           原樣顯示。這裡不做任何形式的翻譯或正規化。 */
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
              text: t("identifier.view_source"),
            })
          : el("span", { class: "dim", text: t("identifier.no_source_photo") }),
        suggestion.identifier_kind || isIdentifierField(suggestion.field)
          ? el("span", {
              class: "dim", style: "font-size:12px",
              text: t("suggestion.will_create_identifier"),
            })
          : null,
        el("span", { style: "flex:1" }),
        decisionButton(suggestion, "reject", t("suggestion.reject")),
        decisionButton(suggestion, "accept", t("suggestion.accept")),
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

  /* 接受／拒絕共用同一組句型，所以訊息用 key 組出來而不是各寫一份。
     這樣新增語言只要補字典，不必在這裡加 if。 */
  const failedKey = action === "accept"
    ? "suggestion.accept_failed" : "suggestion.reject_failed";
  const reloadFailedKey = action === "accept"
    ? "suggestion.accept_ok_reload_failed"
    : "suggestion.reject_ok_reload_failed";

  try {
    await api(
      "/api/suggestions/" + encodeURIComponent(suggestionId) + "/" + action,
      { method: "POST" }
    );
  } catch (err) {
    /* 伺服器沒動 → 建議仍是 pending，把按鈕交回去讓人再試一次 */
    setCardBusy(card, false);
    slot.hidden = false;
    slot.textContent = t(failedKey, { message: err.message });
    return;
  }

  /* 到這裡建議已經被決定了，接下來重載失敗也不能說「接受失敗」 */
  try {
    await refresh();
  } catch (err) {
    /* 訊息放在頁面層級的提示區，不放在那張卡上 ——
       refresh() 可能已經換掉卡片，寫進被移除的節點等於沒寫。
       提示區在 .wrap 頂端、不受 render 影響，而且會捲進視線。 */
    showError(t(reloadFailedKey, { message: err.message }));
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
    ? (decided
        ? t("suggestion.pending_count", { pending: pending.length, decided })
        : t("suggestion.pending_count_only", { pending: pending.length }))
    : "";

  const box = document.getElementById("pending");
  clear(box);
  pending.forEach((item) => box.appendChild(suggestionCard(item, photosById)));
}

/* ------------------------------------------------------------ AI 自動填入 */

/* 照片 → server 端 AI 分析 → pending suggestions。
   分析結果一律是「待確認建議」，要逐筆接受才會寫進商品
   （推論與事實分離）。AI 永不直接改商品欄位。
   接受／拒絕用上面既有的 suggestion 卡片，不另做一套 UI。 */
async function analyzeWithAi() {
  aiButton.disabled = true;
  aiStatus.textContent = t("suggestion.ai_analyzing");
  try {
    const created = await api(
      "/api/items/" + encodeURIComponent(ITEM_ID) + "/ai/analyze",
      { method: "POST" }
    );
    /* 重新載入資料，讓待確認建議卡片出現 */
    await refresh();
    aiStatus.textContent = created.length
      ? t("suggestion.ai_done", { count: created.length })
      : t("suggestion.ai_none");
  } catch (err) {
    aiStatus.textContent = "";
    showError(t("suggestion.ai_failed", { message: err.message }));
  } finally {
    aiButton.disabled = false;
  }
}

aiButton.addEventListener("click", analyzeWithAi);

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
          el("span", { class: "badge", text: enumLabel(IDENTIFIER_LABEL_KEYS, identifier.kind) }),
        ]),
        el("td", {}, [
          el("div", { class: "ident-value" }, [
            /* SPEC §6：識別碼欄位旁永遠顯示來源照片縮圖 */
            source ? sourceThumb(source) : null,
            el("div", {}, [
              el("div", { text: identifier.value }),
              identifier.confidence !== null
                ? el("div", { class: "dim", style: "font-size:12px" }, [
                    t("identifier.confidence", { value: identifier.confidence }) +
                      (identifier.source === "accepted_suggestion"
                        ? t("identifier.from_suggestion") : ""),
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
                    t("identifier.collision"),
                    /* item_id 是資料，原樣顯示。 */
                    el("a", {
                      href: "/items/" + encodeURIComponent(row.item_id),
                      "data-collision-link": row.item_id,
                      text: row.item_id,
                    }),
                    t("identifier.collision_also"),
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
                text: t("identifier.view_source"),
              })
            : el("span", { class: "dim", text: t("common.none") }),
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
        el("td", {}, [el("span", { class: "badge", text: enumLabel(OBSERVATION_KIND_KEYS, observation.kind) })]),
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
                text: t("common.photo_count", { count: photos.length }),
              })
            : el("span", { class: "dim", text: t("common.none") }),
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
    text: t("event.revert"),
    onclick: () => revert(rowFor(event.id), event.id),
  });
}

function rowFor(eventId) {
  return document.querySelector('.event[data-event="' + eventId + '"]');
}

function eventRow(event) {
  const what = el("div", { class: "what" }, [
    el("b", { text: enumLabel(EVENT_TYPE_KEYS, event.type) }),
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
        [enumLabel(EVENT_ACTOR_KEYS, event.actor),
         enumLabel(EVENT_ENTITY_KEYS, event.entity_type)]
          .filter(Boolean).join(" · "),
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
    slot.textContent = t("event.revert_failed", { message: err.message });
    return;
  }

  /* 復原已經發生了。重載失敗不能說「復原失敗」，那會讓人再按一次。 */
  try {
    await refresh();
  } catch (err) {
    /* 訊息放頁面層級：refresh 可能已經把這列換掉，寫進舊節點等於沒寫。
       按鈕維持鎖住 —— 別再對同一個事件按第二次。 */
    showError(t("event.revert_ok_reload_failed", { message: err.message }));
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
  document.getElementById("event-count").textContent =
    t("event.count", { count: events.length });
  if (!events.length) {
    box.appendChild(el("div", { class: "dim", text: t("event.empty") }));
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
    showError(t("item.save_failed", { message: err.message }));
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
    t("item.updated_at", { time: shortTime(updated.updated_at) });
  saved.hidden = false;
  saved.textContent = t("item.saved");
  setTimeout(() => { saved.hidden = true; }, 2000);
  button.disabled = false;

  try {
    renderEvents(await api("/api/items/" + encodeURIComponent(current.id) + "/events"));
  } catch (err) {
    showError(t("item.saved_history_failed", { message: err.message }));
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

  lastItemData = data;
  lastEventsData = events;
  current = data.item;
  detail.hidden = false;

  document.getElementById("head-id").textContent = current.id;
  document.getElementById("head-status").replaceChildren(badge(current.status));
  document.getElementById("updated").textContent =
    t("item.updated_at", { time: shortTime(current.updated_at) });

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

i18nSubscribe(async () => {
  if (!lastItemData || !current) return;
  const headStatus = document.getElementById("head-status");
  if (headStatus) headStatus.replaceChildren(badge(current.status));
  const updatedEl = document.getElementById("updated");
  if (updatedEl) {
    updatedEl.textContent = t("item.updated_at", { time: shortTime(current.updated_at) });
  }
  renderWall(lastItemData.photos);
  const photosById = new Map((lastItemData.photos || []).map((photo) => [photo.id, photo]));
  const byObservation = {};
  (lastItemData.photos || []).forEach((photo) => {
    if (!photo.observation_id) return;
    (byObservation[photo.observation_id] =
      byObservation[photo.observation_id] || []).push(photo);
  });
  renderSuggestions(lastItemData.suggestions || [], photosById);
  await renderIdentifiers(lastItemData.identifiers || [], photosById);
  renderObservations(
    (lastItemData.observations || []).map((observation) => ({
      ...observation,
      photos: byObservation[observation.id] || [],
    })),
    photosById
  );
  if (lastEventsData) renderEvents(lastEventsData);
});

/* ---------------------------------------------------------------- 列印
 *
 * 商品頁的列印只有三件事：挑範本 → 看預覽 → 列印 1 份。
 * 對話框本身（載入預設值、渲染預覽、送出列印）在 ui/print_dialog.js，
 * 與「設定 → 列印」共用同一份。
 *
 * 商品是固定的（就是本頁這一件），所以不給商品下拉 —— 固定值由
 * printOpenDialog(ITEM_ID) 帶進去。
 */

/* print_dialog.js 用這個介面。它的路徑是相對 API 根的（"templates/…"），
   而本頁的 api() 不會自己補 /api（item.js 一直自己寫完整路徑），
   所以這裡補上 —— 讓 print_dialog.js 的介面只有一種路徑形式。 */
printDialogApi = {
  get: (path) => api("/api" + path),
  post: (path, body) =>
    api("/api" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

document.getElementById("print-label").addEventListener("click", async () => {
  document.getElementById("print-head-id").textContent = ITEM_ID;
  await printOpenDialog(ITEM_ID);
});

printBind();

(async function start() {
  /* 語言偏好要在任何 t() 被呼叫之前讀好。放在 async IIFE 的最前面，
     其他頁面的 start() 也是同一個位置 —— 順序反了會先用預設語言畫一次
     再切成偏好語言，使用者會看到閃一下。 */
  i18nInit();
  showError("");
  let loaded = false;
  try {
    await refresh();
    loaded = true;
  } catch (err) {
    notFound.hidden = false;
    showError(err.message);
  }
  /* 連續拍照建檔後導向這裡時帶 ?ai=1：沿用同一條 AI 流程，
     自動把這一批照片送去做分析。結果一樣是待確認建議，
     逐筆接受才會寫進商品（推論與事實分離）。 */
  if (loaded && new URLSearchParams(window.location.search).get("ai") === "1") {
    history.replaceState(null, "", window.location.pathname);
    analyzeWithAi();
  }
})();