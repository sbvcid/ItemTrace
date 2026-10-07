/* 在假 DOM 上跑真正的 ui/settings.js + ui/api.js。

  重點：這支程式碼永遠拿不到已儲存的 API key —— GET 不回傳它，
  密碼欄每次載入都是空的。顯示／隱藏切換只影響「使用者剛輸入的字」。
*/

const { mount } = require("./dom_stubs");

function makeHarness(options = {}) {
  const calls = [];
  const responses = {
    "/api/settings/ai": {
      provider: options.provider || "openrouter",
      configured: options.configured !== false,
      model: options.model || "seed/model:free",
      base_url: options.baseUrl || "https://openrouter.ai/api/v1",
      default_model: "qwen/qwen3.8-27b:free",
      presets: {
        openrouter: "https://openrouter.ai/api/v1",
        google: "https://generativelanguage.googleapis.com/v1beta/openai",
      },
      can_edit: true,
      is_loopback: options.loopback !== false,
      config_file: "tools/ai_config.local.json",
    },
    save: options.saveResponse || {
      provider: "openrouter", configured: true, model: "new/model:free",
      base_url: "https://openrouter.ai/api/v1",
      api_key_changed: false, model_changed: true,
      provider_changed: false, base_url_changed: false,
    },
    test: options.testResponse || { ok: true, model: "new/model:free", detail: "" },
    clear: { provider: "openrouter", configured: false,
             model: "new/model:free", base_url: "https://openrouter.ai/api/v1",
             api_key_changed: true, model_changed: false },
    ...(options.responses || {}),
  };

  const confirmAnswer = options.confirmAnswer !== false;

  const view = mount({
    scripts: ["api.js", "settings.js"],
    windowProps: {
      location: { href: "", pathname: "/settings", origin: "http://127.0.0.1" },
      confirm: () => confirmAnswer,
    },
    fetchImpl: async (path, init) => {
      const method = (init && init.method) || "GET";
      calls.push({ path, method, body: init && init.body ? JSON.parse(init.body) : null });

      if (method === "GET" && path === "/api/settings/ai") {
        return ok(responses["/api/settings/ai"]);
      }
      if (path === "/api/settings/ai/test") {
        return options.testError
          ? fail(400, options.testError)
          : ok(responses.test);
      }
      if (path === "/api/settings/ai/clear-key") return ok(responses.clear);
      if (path === "/api/settings/ai" && method === "POST") {
        return options.saveError ? fail(400, options.saveError) : ok(responses.save);
      }
      return ok({});
    },
  });

  const el = (id) => view.element(id);
  /* 照 settings.html 的 markup 設定初始型別：密碼欄是 type="password"，
     顯示/隱藏切換的行為才和瀏覽器一致。 */
  el("api-key").type = "password";
  el("model").type = "text";
  return {
    view, calls, el,
    get value() { return el("api-key").value; },
    setValue(v) { el("api-key").value = v; },
    model() { return el("model").value; },
    setModel(v) { el("model").value = v; },
    provider() { return el("provider").value; },
    setProvider(v) { el("provider").value = v; },
    baseUrl() { return el("base-url").value; },
    setBaseUrl(v) { el("base-url").value = v; },
    keyState() { return el("key-state").textContent; },
    status() { return el("status").textContent; },
    errorText() {
      return el("error").childNodes.map((c) => c.textContent).join(" | ");
    },
    lanWarningHidden() { return el("lan-warning").hidden; },
    disabled() {
      return ["api-key", "model", "provider", "base-url",
              "save", "test", "clear"]
        .map((id) => el(id).disabled);
    },
    type() { return el("api-key").type; },
    toggleLabel() { return el("toggle").textContent; },
    async click(id) {
      const button = el(id);
      await Promise.all((button.listeners.click || []).map((fn) => fn({})));
      await view.flush();
    },
    async submit() {
      const form = el("form") || { listeners: {} };
      /* settings.js 是綁在按鈕上，不是 form submit */
      await Promise.all((el("save").listeners.click || []).map((fn) => fn({})));
      await view.flush();
    },
    async run() { await view.flush(); },
  };
}

function ok(body) {
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
}
function fail(status, detail) {
  return { ok: false, status, text: async () => JSON.stringify({ detail }) };
}

const label = (text) => String(text);

(async () => {
  const results = [];

  // 載入：顯示已設定，密碼欄留白
  let h = makeHarness();
  await h.run();
  results.push({
    label: "已設定時載入",
    keyState: h.keyState(),
    keyValue: h.value,
    model: h.model(),
    provider: h.provider(),
    baseUrl: h.baseUrl(),
    lanWarningHidden: h.lanWarningHidden(),
    disabled: h.disabled(),
    errorText: h.errorText(),
    configFile: h.el("config-file").textContent,
  });

  // 未設定
  h = makeHarness({ configured: false });
  await h.run();
  results.push({
    label: "未設定時載入",
    keyState: h.keyState(),
    keyValue: h.value,
    model: h.model(),
    disabled: h.disabled(),
    errorText: h.errorText(),
  });

  // 區網：看得到、也能改（server 刻意只服務受信任區網）
  h = makeHarness({ loopback: false });
  await h.run();
  results.push({
    label: "區網檢視",
    keyState: h.keyState(),
    model: h.model(),
    lanWarningHidden: h.lanWarningHidden(),
    disabled: h.disabled(),
  });

  // 只改 model
  h = makeHarness();
  await h.run();
  h.setModel("new/model:free");
  await h.click("save");
  results.push({
    label: "只改 model",
    posted: h.calls.filter((c) => c.method === "POST"),
    status: h.status(),
    keyValue: h.value,
    errorText: h.errorText(),
  });

  // 改 key
  h = makeHarness();
  await h.run();
  h.setValue("sk-or-v1-TEST-LOCAL-KEY");
  await h.click("save");
  results.push({
    label: "改 API key",
    posted: h.calls.filter((c) => c.method === "POST"),
    status: h.status(),
    keyValueAfter: h.value,
    keyState: h.keyState(),
  });

  // 切換 provider → 自動帶入該 provider 的預設 base URL
  h = makeHarness();
  await h.run();
  h.setProvider("google");
  await h.el("provider").fire("change");
  results.push({
    label: "切換 provider",
    provider: h.provider(),
    baseUrl: h.baseUrl(),
  });

  // 儲存失敗
  h = makeHarness({ saveError: "base_url：base_url 必須是 http/https URL" });
  await h.run();
  h.setModel("x/y:free");
  await h.click("save");
  results.push({
    label: "儲存失敗",
    status: h.status(),
    errorText: h.errorText(),
    keyValue: h.value,
  });

  // 測試 API 成功
  h = makeHarness();
  await h.run();
  await h.click("test");
  results.push({
    label: "測試 API 成功",
    posted: h.calls.filter((c) => c.path.includes("/test")),
    status: h.status(),
    errorText: h.errorText(),
  });

  // 測試 API 失敗
  h = makeHarness({ testError: "API 測試失敗（401）：{\"error\":{\"message\":\"No auth\"}}" });
  await h.run();
  await h.click("test");
  results.push({
    label: "測試 API 失敗",
    status: h.status(),
    errorText: h.errorText(),
  });

  // 測試剛貼上還沒存的 key
  h = makeHarness();
  await h.run();
  h.setValue("sk-or-v1-UNSAVED-KEY-000000");
  h.setModel("typed/model:free");
  await h.click("test");
  results.push({
    label: "測試未儲存的 key",
    posted: h.calls.filter((c) => c.path.includes("/test")),
    status: h.status(),
  });

  // 清除（使用者取消）
  h = makeHarness({ confirmAnswer: false });
  await h.run();
  await h.click("clear");
  results.push({
    label: "清除但取消",
    cleared: h.calls.some((c) => c.path.includes("clear-key")),
    status: h.status(),
  });

  // 清除（使用者確認）
  h = makeHarness({ confirmAnswer: true });
  await h.run();
  await h.click("clear");
  results.push({
    label: "清除並確認",
    cleared: h.calls.some((c) => c.path.includes("clear-key")),
    status: h.status(),
    keyState: h.keyState(),
    keyValue: h.value,
  });

  // 顯示／隱藏
  h = makeHarness();
  await h.run();
  const beforeType = h.type();
  await h.click("toggle");
  const afterType = h.type();
  const label1 = h.toggleLabel();
  await h.click("toggle");
  results.push({
    label: "顯示隱藏切換",
    beforeType, afterType, backType: h.type(),
    labelAfterShow: label1,
    labelAfterHide: h.toggleLabel(),
  });

  process.stdout.write(JSON.stringify(results, null, 2));
})();
