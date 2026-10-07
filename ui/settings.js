/* /settings —— 在網頁上設定 AI 服務的 API key、provider 與 model。

   這支程式碼裡永遠不會出現已儲存的 API key：GET /api/settings/ai
   不回傳它，密碼欄每次載入都是空的。顯示／隱藏切換只影響
   「使用者剛剛輸入的字」，不會把已儲存的 key 叫回來 ——
   那等於把 secret 送到瀏覽器。
*/

const apiKeyInput = document.getElementById("api-key");
const toggleBtn = document.getElementById("toggle");
const modelInput = document.getElementById("model");
const providerInput = document.getElementById("provider");
const baseUrlInput = document.getElementById("base-url");
const saveBtn = document.getElementById("save");
const testBtn = document.getElementById("test");
const clearBtn = document.getElementById("clear");
const statusBox = document.getElementById("status");
const keyState = document.getElementById("key-state");
const lanWarning = document.getElementById("lan-warning");

let canEdit = false;
let configured = false;
let modelWas = "";
let providerWas = "";
let baseUrlWas = "";
let isLoopback = true;

/* 已知 provider 的預設 base URL 來自 GET 回應的 presets
   （後端是唯一來源，這裡不刻一份靜態清單）。 */
let presets = {};

function setStatus(message, kind) {
  clear(statusBox);
  if (!message) return;
  statusBox.appendChild(el("div", { class: "status-" + (kind || "info"), text: message }));
}

function setEditable(editable) {
  [apiKeyInput, modelInput, providerInput, baseUrlInput,
   saveBtn, testBtn, clearBtn].forEach((node) => {
    node.disabled = !editable;
  });
  if (!editable) {
    apiKeyInput.placeholder = t("settings.readonly_placeholder");
    modelInput.title = t("settings.readonly_title");
  }
  applyProviderPreset();
}

/* 預設 provider 的 base_url 由後端決定，選定後帶入並鎖住；
   Custom 才讓使用者自己填任何 OpenAI 相容端點。 */
function applyProviderPreset() {
  const preset = presets[providerInput.value];
  const custom = providerInput.value === "custom";
  baseUrlInput.readOnly = !!preset && !custom;
  if (preset && !custom && baseUrlInput.value !== preset) {
    baseUrlInput.value = preset;
  }
}

async function load() {
  let settings;
  try {
    settings = await api("/api/settings/ai");
  } catch (err) {
    showError(t("settings.load_failed", { message: err.message }));
    setEditable(false);
    return;
  }

  document.getElementById("config-file").textContent = settings.config_file;
  modelInput.value = settings.model;
  modelInput.placeholder = settings.default_model;
  modelWas = settings.model;
  configured = settings.configured;
  canEdit = settings.can_edit;
  isLoopback = settings.is_loopback;
  presets = settings.presets || {};

  providerInput.value = settings.provider;
  providerWas = settings.provider;
  baseUrlInput.value = settings.base_url;
  baseUrlWas = settings.base_url;

  // 已儲存的 key 不會回傳，這裡只顯示「有沒有設定」
  keyState.textContent = t(
    configured ? "settings.api_key_set" : "settings.api_key_unset"
  );
  apiKeyInput.value = "";

  setEditable(canEdit);
  lanWarning.hidden = isLoopback;
}

async function save() {
  showError("");
  setStatus(t("settings.saving"), "info");
  const body = {
    model: modelInput.value.trim(),
    provider: providerInput.value,
    base_url: baseUrlInput.value.trim(),
  };
  const typed = apiKeyInput.value.trim();
  if (typed) body.api_key = typed;

  try {
    const saved = await api("/api/settings/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    configured = saved.configured;
    modelWas = saved.model;
    providerWas = saved.provider;
    baseUrlWas = saved.base_url;
    apiKeyInput.value = "";
    keyState.textContent = t(
      saved.configured ? "settings.api_key_set" : "settings.api_key_unset"
    );
    const parts = [t("settings.saved")];
    if (saved.api_key_changed) parts.push(t("settings.saved_key"));
    if (saved.model_changed) parts.push(t("settings.saved_model"));
    if (saved.provider_changed) parts.push(t("settings.saved_provider"));
    if (saved.base_url_changed) parts.push(t("settings.saved_base_url"));
    setStatus(parts.join(" · "), "ok");
  } catch (err) {
    setStatus("");
    showError(t("settings.save_failed", { message: err.message }));
  }
}

async function testApi() {
  showError("");
  setStatus(t("settings.testing"), "info");
  const body = {
    model: modelInput.value.trim(),
    provider: providerInput.value,
    base_url: baseUrlInput.value.trim(),
  };
  const typed = apiKeyInput.value.trim();
  if (typed) body.api_key = typed;

  try {
    const result = await api("/api/settings/ai/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    /* result.model 是設定值（資料），原樣顯示；翻譯的是句子。 */
    setStatus(t("settings.test_ok", { model: result.model }), "ok");
  } catch (err) {
    setStatus("");
    showError(t("settings.test_failed", { message: err.message }));
  }
}

async function clearKey() {
  showError("");
  setStatus("");
  const sure = window.confirm(t("settings.clear_confirm"));
  if (!sure) return;
  try {
    await api("/api/settings/ai/clear-key", { method: "POST" });
    configured = false;
    apiKeyInput.value = "";
    keyState.textContent = t("settings.api_key_unset");
    setStatus(t("settings.clear_done"), "ok");
  } catch (err) {
    showError(t("settings.clear_failed", { message: err.message }));
  }
}

/* 按鈕目前處於「顯示」還是「隱藏」。

   為什麼記成變數而不是 data 屬性：切換語言時要重算按鈕文字，而那時
   apiKeyInput.type 已經被改過。存成變數是這裡唯一需要的東西，而且
   刻意不碰任何 DOM 屬性 —— tests/test_settings_ui.py 有一條規則禁止
   在 key 輸入框附近使用 dataset / setAttribute，理由是「已輸入的 key
   不該被寫進任何會留在 DOM 上的地方」。用變數不會踩到那條規則，也就不
   需要為它開例外。 */
let keyIsShown = false;

toggleBtn.addEventListener("click", () => {
  /* 只切換「剛輸入的內容」，不會去取回已儲存的 key */
  const hidden = apiKeyInput.type === "password";
  apiKeyInput.type = hidden ? "text" : "password";
  keyIsShown = hidden;
  toggleBtn.textContent = t(hidden ? "settings.hide" : "settings.show");
});

/* ------------------------------------------------------------ 語言切換訂閱 */

i18nSubscribe(() => {
  /* i18nSwitch 已重新套用 markup 上所有 data-i18n，也會更新 <html lang>。
     下面補的是不在 markup data-i18n 範圍內、JS 產生或依狀態決定的文字。 */
  setEditable(canEdit);
  keyState.textContent = t(
    configured ? "settings.api_key_set" : "settings.api_key_unset"
  );
  /* 顯示／隱藏按鈕：只有在「顯示中」時才顯示「隱藏」。 */
  toggleBtn.textContent = t(keyIsShown ? "settings.hide" : "settings.show");
});

providerInput.addEventListener("change", applyProviderPreset);

saveBtn.addEventListener("click", save);
testBtn.addEventListener("click", testApi);
clearBtn.addEventListener("click", clearKey);
apiKeyInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") save();
});

i18nInit();
load();
