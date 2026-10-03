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

async function run(fileCount, label) {
  /* 用真的 File 物件：node 的 FormData 只接受 Blob/File，
     用假物件會測不到真正的 append 路徑。 */
  const files = Array.from({ length: fileCount }, (_, i) =>
    new File([`photo-${i}`], `IMG_${i}.jpg`, { type: "image/jpeg" })
  );

  const fileInput = makeFileInput(files);
  const requests = [];

  const view = mount({
    scripts: ["api.js", "inbox.js"],
    documentOverrides: { "file-input": fileInput },
    fetchImpl: async (path, options) => {
      requests.push({ path, method: (options && options.method) || "GET", options });
      const payload = path.includes("/group") ? "[]" : '{"entries":[],"count":0}';
      return { ok: true, status: 200, text: async () => payload };
    },
  });

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
  };
}

(async () => {
  const results = [];
  for (const count of [0, 1, 3, 8]) {
    results.push(await run(count, `${count} photos`));
  }
  process.stdout.write(JSON.stringify(results, null, 2));
})();