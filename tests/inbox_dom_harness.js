/* 用 node 的 vm 在假的 DOM 上跑真正的 ui/inbox.js。
 *
 * 為什麼要這樣：pytest 讀原始碼做字串比對，擋得住「忘了清 value」，
 * 擋不住「清 value 之後 FileList 被清空」這種語義錯誤 ——
 * 8d2d2b9 就是這樣壞掉的。所以這裡測行為：真的派發 change 事件，
 * 看 upload() 到底收到幾個 File。
 *
 * 假的 file input 照 HTML Standard 建模：value = "" 會清空 selected
 * files，而 files getter 在清單沒改變時回傳同一個（活的）FileList 物件。
 *
 * 輸出 JSON 給 pytest 讀。執行：node tests/inbox_dom_harness.js
 */

const { mount, makeFileInput } = require("./dom_stubs");

async function run(fileCount, label, options = {}) {
  /* 用真的 File 物件：node 的 FormData 只接受 Blob/File，
     用假物件會測不到真正的 append 路徑。 */
  const files = Array.from({ length: fileCount }, (_, i) =>
    new File([`photo-${i}`], `IMG_${i}.jpg`, { type: "image/jpeg" })
  );

  const fileInput = makeFileInput(files);
  const requests = [];
  const shown = [];
  let posted = false;

  const view = mount({
    scripts: ["api.js", "inbox.js"],
    documentOverrides: { "file-input": fileInput },
    fetchImpl: async (path, requestInit) => {
      requests.push({ path, method: (requestInit && requestInit.method) || "GET",
                      options: requestInit });

      /* Phase 10：POST 與後續 refresh 的失敗必須分開處理。
         只在「已經上傳成功之後」的那次重新載入才失敗 —— mount 時 start()
         也會抓一次 /api/inbox，那次要正常。 */
      if (options.uploadError && path === "/api/inbox/photos") {
        return { ok: false, status: options.uploadError,
                 text: async () => JSON.stringify({ detail: options.uploadDetail || "上傳失敗" }) };
      }
      if (posted && options.reloadError && path === "/api/inbox" && !requestInit) {
        return { ok: false, status: options.reloadError,
                 text: async () => JSON.stringify({ detail: options.reloadDetail || "清單載入失敗" }) };
      }
      if (path === "/api/inbox/photos") posted = true;

      const payload = path.includes("/group") ? "[]" : '{"entries":[],"count":0}';
      return { ok: true, status: 200, text: async () => payload };
    },
  });

  /* start() 會在 mount 時就啟動，showError 要在它之後才攔得到 */
  const realShowError = view.sandbox.showError;
  if (typeof realShowError === "function") {
    view.sandbox.showError = (message) => {
      shown.push(String(message));
      return realShowError(message);
    };
  }

  await fileInput.fireChange();
  await view.flush();

  const upload = requests.find((r) => r.path === "/api/inbox/photos");
  const sent = upload && upload.options.body
    ? upload.options.body.getAll("files").map((f) => f.name)
    : null;

  return {
    label,
    requested: fileCount,
    posted: Boolean(upload),
    method: upload ? upload.method : null,
    fieldNames: upload && upload.options.body
      ? [...new Set(upload.options.body.keys())]
      : [],
    sentNames: sent,
    sentCount: sent ? sent.length : 0,
    fileInputCleared: fileInput.value === "",
    /* Phase 10：錯誤訊息與重載是否真的發生 */
    shownErrors: shown,
    reloaded: requests.some((r) => r.path === "/api/inbox" && !r.options),
    startBtnDisabled: view.element("start").disabled,
    statusText: view.element("upload-status").textContent,
  };
}

(async () => {
  const results = [];
  for (const count of [0, 1, 3, 8]) {
    results.push(await run(count, `${count} photos`));
  }
  /* Phase 10：上傳失敗 vs 上傳成功但重載失敗 */
  results.push(await run(2, "上傳失敗 500", {
    uploadError: 500, uploadDetail: "伺服器爆了",
  }));
  results.push(await run(2, "上傳失敗 413", {
    uploadError: 413, uploadDetail: "檔案太大",
  }));
  results.push(await run(2, "上傳成功但重載失敗", {
    reloadError: 503, reloadDetail: "清單服務暫時無法回應",
  }));
  process.stdout.write(JSON.stringify(results, null, 2));
})();