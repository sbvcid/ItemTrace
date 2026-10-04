/* /settings —— 在網頁上設定 OpenRouter API key 與 model。

  這支程式碼裡永遠不會出現已儲存的 API key：GET /api/settings/ai 不回傳它，
  密碼欄每次載入都是空的。顯示／隱藏切換只影響「使用者剛剛輸入的字」，
  不會把已儲存的 key 叫回來 —— 那等於把 secret 送到瀏覽器。
*/

const apiKeyInput = document.getElementById("api-key");
const toggleBtn = document.getElementById("toggle");
const modelInput = document.getElementById("model");
const saveBtn = document.getElementById("save");
const testBtn = document.getElementById("test");
const clearBtn = document.getElementById("clear");
const statusBox = document.getElementById("status");
const keyState = document.getElementById("key-state");
const lanWarning = document.getElementById("lan-warning");

let canEdit = false;
let configured = false;
let modelWas = "";

function setStatus(message, kind) {
  clear(statusBox);
  if (!message) return;
  statusBox.appendChild(el("div", { class: "status-" + (kind || "info"), text: message }));
}

function setEditable(editable) {
  [apiKeyInput, modelInput, saveBtn, testBtn, clearBtn].forEach((node) => {
    node.disabled = !editable;
  });
  if (!editable) {
    apiKeyInput.placeholder = "只有本機可以修改";
    modelInput.title = "只有本機可以修改";
  }
}

async function load() {
  let settings;
  try {
    settings = await api("/api/settings/ai");
  } catch (err) {
    showError("讀取設定失敗：" + err.message);
    setEditable(false);
    return;
  }

  document.getElementById("config-file").textContent = settings.config_file;
  modelInput.value = settings.model;
  modelInput.placeholder = settings.default_model;
  modelWas = settings.model;
  configured = settings.configured;
  canEdit = settings.can_edit;

  // 已儲存的 key 不會回傳，這裡只顯示「有沒有設定」
  keyState.textContent = configured
    ? "API Key：已設定（不會顯示實際內容）"
    : "API Key：未設定";
  apiKeyInput.value = "";

  setEditable(canEdit);
  lanWarning.hidden = canEdit;
}

async function save() {
  showError("");
  setStatus("儲存中…", "info");
  const body = { model: modelInput.value.trim() };
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
    apiKeyInput.value = "";
    keyState.textContent = saved.configured
      ? "API Key：已設定（不會顯示實際內容）"
      : "API Key：未設定";
    const parts = ["設定已儲存"];
    if (saved.api_key_changed) parts.push("API key 已更新");
    if (saved.model_changed) parts.push("model 已更新");
    setStatus(parts.join(" · "), "ok");
  } catch (err) {
    setStatus("");
    showError("儲存失敗：" + err.message);
  }
}

async function testApi() {
  showError("");
  setStatus("測試中…（會送出一次最小請求）", "info");
  const body = { model: modelInput.value.trim() };
  const typed = apiKeyInput.value.trim();
  if (typed) body.api_key = typed;

  try {
    const result = await api("/api/settings/ai/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setStatus("API 測試成功（model " + result.model + "）", "ok");
  } catch (err) {
    setStatus("API 測試失敗", "bad");
    showError(err.message);
  }
}

async function clearKey() {
  showError("");
  setStatus("");
  const sure = window.confirm(
    "確定要清除 API Key 嗎？\n\n清除後 AI adapter 就不能用了，" +
    "需要重新貼上 key 才能使用。Model 會保留。"
  );
  if (!sure) return;
  try {
    await api("/api/settings/ai/clear-key", { method: "POST" });
    configured = false;
    apiKeyInput.value = "";
    keyState.textContent = "API Key：未設定";
    setStatus("API Key 已清除", "ok");
  } catch (err) {
    showError("清除失敗：" + err.message);
  }
}

toggleBtn.addEventListener("click", () => {
  /* 只切換「剛輸入的內容」，不會去取回已儲存的 key */
  const hidden = apiKeyInput.type === "password";
  apiKeyInput.type = hidden ? "text" : "password";
  toggleBtn.textContent = hidden ? "隱藏" : "顯示";
});

saveBtn.addEventListener("click", save);
testBtn.addEventListener("click", testApi);
clearBtn.addEventListener("click", clearKey);
apiKeyInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") save();
});

load();
