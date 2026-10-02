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

/* ---------------------------------------------------------------- 建議 */

function renderSuggestions(items) {
  const pending = items.filter((item) => item.status === "pending");
  document.getElementById("pending-sec").hidden = pending.length === 0;
  document.getElementById("pending-count").textContent =
    pending.length ? "（" + pending.length + " 筆）" : "";

  const box = document.getElementById("pending");
  clear(box);
  pending.forEach((item) => {
    box.appendChild(
      el("div", { class: "sugg" }, [
        el("div", {}, [
          el("b", { text: item.field }),
          " → ",
          el("span", { text: item.value }),
        ]),
        el("div", { class: "dim", style: "font-size:12.5px;margin-top:4px" }, [
          item.confidence !== null ? "信心 " + item.confidence + " · " : "",
          item.model_name ? item.model_name : "",
          item.source_photo_id ? " · 有來源照片" : "",
        ]),
      ])
    );
  });
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
        el("td", {}, [el("span", { class: "badge", text: identifier.kind })]),
        el("td", {}, [
          el("div", { text: identifier.value }),
          identifier.confidence !== null
            ? el("div", { class: "dim", style: "font-size:12px" }, [
                "信心 " + identifier.confidence +
                  (identifier.source === "accepted_suggestion" ? " · 來自建議" : ""),
              ])
            : null,
          conflict
            ? el("div", { class: "badge warn", style: "margin-top:4px" }, [
                "⚠ 撞號：" +
                  conflict
                    .map((row) => row.item_id + " 也有相同識別碼")
                    .join("、"),
              ])
            : null,
        ]),
        el("td", {},
          source
            ? el("a", {
                href: photoUrl(source.filename),
                target: "_blank",
                rel: "noopener",
                text: "看來源照片",
              })
            : el("span", { class: "dim", text: "—" })
        ),
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

function renderEvents(events) {
  const box = document.getElementById("events");
  clear(box);
  document.getElementById("event-count").textContent = String(events.length);
  if (!events.length) {
    box.appendChild(el("div", { class: "dim", text: "沒有紀錄" }));
    return;
  }
  events.forEach((event) => {
    const what = el("div", { class: "what" }, [
      el("b", { text: event.type }),
      event.field ? " · " + event.field : "",
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
    box.appendChild(
      el("div", { class: "event" }, [
        el("div", { class: "when", text: shortTime(event.created_at) }),
        el("div", {}, [what, el("div", { class: "dim", style: "font-size:12px" },
          [event.actor, event.entity_type].filter(Boolean).join(" · "))]),
      ])
    );
  });
}

/* -------------------------------------------------------------- 編輯 */

function fillForm(item) {
  FIELDS.forEach((name) => {
    field(name).value = item[name] === null ? "" : item[name];
  });
  dirty = new Set();
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
  try {
    const updated = await api("/api/items/" + encodeURIComponent(current.id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    current = updated;
    FIELDS.forEach((name) => { field(name).value = updated[name]; });
    dirty = new Set();
    document.getElementById("head-status").replaceChildren(badge(updated.status));
    document.getElementById("updated").textContent =
      "更新於 " + shortTime(updated.updated_at);
    saved.hidden = false;
    saved.textContent = "已儲存";
    setTimeout(() => { saved.hidden = true; }, 2000);
    renderEvents(await api("/api/items/" + encodeURIComponent(current.id) + "/events"));
  } catch (err) {
    showError("儲存失敗：" + err.message);
  } finally {
    button.disabled = false;
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

(async function start() {
  showError("");
  try {
    const data = await api("/api/items/" + encodeURIComponent(ITEM_ID));
    current = data.item;
    detail.hidden = false;

    document.getElementById("head-id").textContent = current.id;
    document.getElementById("head-status").replaceChildren(badge(current.status));
    document.getElementById("updated").textContent =
      "更新於 " + shortTime(current.updated_at);

    fillForm(current);
    renderWall(data.photos);

    const photosById = new Map(data.photos.map((photo) => [photo.id, photo]));
    const byObservation = {};
    data.photos.forEach((photo) => {
      if (!photo.observation_id) return;
      (byObservation[photo.observation_id] =
        byObservation[photo.observation_id] || []).push(photo);
    });

    renderSuggestions(data.suggestions || []);
    await renderIdentifiers(data.identifiers || [], photosById);
    renderObservations(
      (data.observations || []).map((observation) => ({
        ...observation,
        photos: byObservation[observation.id] || [],
      })),
      photosById
    );
    renderEvents(await api("/api/items/" + encodeURIComponent(ITEM_ID) + "/events"));
    loadCategories();
  } catch (err) {
    notFound.hidden = false;
    showError(err.message);
  }
})();