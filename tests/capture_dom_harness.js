/* 在假 DOM 上跑真正的 ui/capture.js + ui/api.js。

  重點驗證：
    * 快門是唯一的相機觸發路徑（cameraInput.click() 只在 shutter handler）
    * 拍攝累積：2 / 5 / 10 張，張數正確，input 被清空（同一張能再拍）
    * 完成 → 預覽本批；刪單張；繼續拍攝
    * 取消整批：什麼都沒上傳、沒有 POST、導向首頁
    * 建檔：前後差集 → POST /api/inbox/photos → /api/inbox/intake
      → 導向 /items/<id>?ai=1
*/

const { mount } = require("./dom_stubs");

/* 假相機回傳的檔案：Node 的 Blob + name，FormData 吃得下。 */
function fakeFile(name) {
  return Object.assign(new Blob(["fake-" + name], { type: "image/jpeg" }), {
    name,
  });
}

function makeHarness(options = {}) {
  const calls = [];
  /* 模擬 inbox：已有一張舊照片，驗證「前後差集」只抓到新批次 */
  const inbox = ["inbox/old.jpg"];
  const state = {
    cameraClicks: 0,
    intakeBody: null,
    uploadedNames: [],
    location: "",
  };

  const view = mount({
    scripts: ["api.js", "capture.js"],
    windowProps: {
      location: { href: "", pathname: "/capture", origin: "http://127.0.0.1" },
    },
    fetchImpl: async (path, init) => {
      const method = (init && init.method) || "GET";
      calls.push({ path, method, body: init && init.body ? init.body : null });

      if (path === "/api/inbox" && method === "GET") {
        return ok({
          entries: inbox.map((relative) => ({
            relative, captured_at: null, captured_from: "none", bytes: 0,
          })),
          count: inbox.length,
        });
      }
      if (path === "/api/inbox/photos" && method === "POST") {
        const names = init.body.getAll("files").map((file) => file.name);
        state.uploadedNames = names;
        names.forEach((name) => inbox.push("inbox/" + name));
        return ok({ count: inbox.length });
      }
      if (path === "/api/inbox/intake" && method === "POST") {
        state.intakeBody = JSON.parse(init.body);
        if (options.intakeError) return fail(400, options.intakeError);
        return ok({
          item_id: "ITM-0001", observation_id: "OBS-0001",
          archived: [], skipped: [],
        });
      }
      return ok({});
    },
  });

  const el = (id) => view.element(id);
  /* 記錄相機被開了幾次（capture.js 只能從快門觸發它） */
  el("camera-input").click = () => { state.cameraClicks += 1; };

  /* 模擬「拍完一張，相機關掉、把檔案交回來」 */
  async function shoot(names) {
    el("camera-input").files = names.map(fakeFile);
    await el("camera-input").fire("change");
  }

  async function click(id) {
    const button = el(id);
    await Promise.all((button.listeners.click || []).map((fn) => fn({})));
    await view.flush();
  }

  return {
    view, calls, el, state, shoot, click,
    countText: () => el("count").textContent,
    stripLength: () => el("strip").childNodes.length,
    gridLength: () => el("grid").childNodes.length,
    captureHidden: () => el("capture-sec").hidden,
    previewHidden: () => el("preview-sec").hidden,
    finishDisabled: () => el("finish").disabled,
    buildDisabled: () => el("build").disabled,
    errorText: () => el("error").textContent,
    inputValue: () => el("camera-input").value,
    /* capture.js 設的是 sandbox 裡 window.location.href */
    href: () => view.sandbox.window.location.href,
  };
}

function ok(body) {
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
}
function fail(status, detail) {
  return { ok: false, status, text: async () => JSON.stringify({ detail }) };
}

(async () => {
  const results = [];

  // 進入連續拍照：空批次、完成按鈕鎖住、預覽藏起來
  let h = makeHarness();
  await h.view.flush();
  results.push({
    label: "進入連續拍照",
    countText: h.countText(),
    finishDisabled: h.finishDisabled(),
    previewHidden: h.previewHidden(),
    stripLength: h.stripLength(),
  });

  // 快門 → 相機直接開（只記錄 click，不真的開檔案選擇器）
  await h.click("shutter");
  results.push({
    label: "快門開相機",
    cameraClicks: h.state.cameraClicks,
  });

  // 連續拍 2 張（一次一張，手機相機的實際行為）
  h = makeHarness();
  await h.view.flush();
  await h.shoot(["IMG_1.jpg"]);
  await h.shoot(["IMG_2.jpg"]);
  results.push({
    label: "連續拍 2 張",
    countText: h.countText(),
    stripLength: h.stripLength(),
    inputCleared: h.inputValue() === "",
  });

  // 連續拍 5 張
  h = makeHarness();
  await h.view.flush();
  for (const name of ["A.jpg", "B.jpg", "C.jpg", "D.jpg", "E.jpg"]) {
    await h.shoot([name]);
  }
  results.push({
    label: "連續拍 5 張",
    countText: h.countText(),
    stripLength: h.stripLength(),
  });

  // 連續拍 10 張（strip 只顯示最近 8 張 + 多餘的 +N）
  h = makeHarness();
  await h.view.flush();
  for (let i = 1; i <= 10; i += 1) await h.shoot(["p" + i + ".jpg"]);
  results.push({
    label: "連續拍 10 張",
    countText: h.countText(),
    stripLength: h.stripLength(),
    finishDisabled: h.finishDisabled(),
  });

  // 完成 → 預覽本批；刪一張；繼續拍攝
  h = makeHarness();
  await h.view.flush();
  for (const name of ["A.jpg", "B.jpg", "C.jpg"]) await h.shoot([name]);
  await h.click("finish");
  const beforeDelete = {
    previewHidden: h.previewHidden(),
    gridLength: h.gridLength(),
    previewCount: h.el("preview-count").textContent,
    buildDisabled: h.buildDisabled(),
  };
  // 刪除單張：grid 裡第一個 remove 按鈕
  const removeButton = h.view.query(".remove");
  await Promise.all((removeButton.listeners.click || []).map((fn) => fn({})));
  await h.view.flush();
  const afterDelete = {
    gridLength: h.gridLength(),
    countText: h.countText(),
  };
  // 繼續拍攝：回到快門畫面
  await h.click("continue");
  results.push({
    label: "預覽本批",
    ...beforeDelete,
    afterDelete,
    backToCapture: !h.captureHidden() && h.previewHidden(),
  });

  // 取消整批：沒有 POST、導向首頁
  h = makeHarness();
  await h.view.flush();
  for (const name of ["A.jpg", "B.jpg"]) await h.shoot([name]);
  await h.click("cancel");
  results.push({
    label: "取消整批",
    posts: h.calls.filter((c) => c.method === "POST").length,
    href: h.href(),
    countText: h.countText(),
  });

  // 取消整批（在預覽畫面）
  h = makeHarness();
  await h.view.flush();
  await h.shoot(["A.jpg"]);
  await h.click("finish");
  await h.click("discard");
  results.push({
    label: "預覽畫面取消整批",
    posts: h.calls.filter((c) => c.method === "POST").length,
    href: h.href(),
  });

  // 建檔：前後差集 → 上傳 → intake → 導向商品頁 ?ai=1
  h = makeHarness();
  await h.view.flush();
  for (const name of ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"]) {
    await h.shoot([name]);
  }
  await h.click("finish");
  await h.click("build");
  results.push({
    label: "建檔",
    calls: h.calls.map((c) => ({
      path: c.path,
      method: c.method,
      files: c.body && c.body.getAll
        ? c.body.getAll("files").map((f) => f.name)
        : (c.body ? JSON.parse(c.body).files : undefined),
    })),
    uploadedNames: h.state.uploadedNames,
    intakeFiles: h.state.intakeBody && h.state.intakeBody.files,
    intakeKind: h.state.intakeBody && h.state.intakeBody.kind,
    href: h.href(),
  });

  // 建檔失敗（intake 400）：照片留在 inbox，錯誤顯示，不導向
  h = makeHarness({ intakeError: "kind：值不合法" });
  await h.view.flush();
  await h.shoot(["A.jpg"]);
  await h.click("finish");
  await h.click("build");
  results.push({
    label: "建檔失敗",
    errorText: h.errorText(),
    href: h.href(),
    posts: h.calls.filter((c) => c.method === "POST").length,
  });

  // 空批次：建檔按鈕鎖住，按了也不送出
  h = makeHarness();
  await h.view.flush();
  await h.click("finish");
  await h.click("build");
  results.push({
    label: "空批次",
    buildDisabled: h.buildDisabled(),
    posts: h.calls.filter((c) => c.method === "POST").length,
  });

  process.stdout.write(JSON.stringify(results, null, 2));
})();
