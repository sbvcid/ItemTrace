/** UI Showcase page logic - reuse existing patterns, no new design language. */

/* ====== Locale ====== */
function fillLocaleOptions() {
  const localeSelect = document.getElementById("locale");
  if (!localeSelect) return;
  const LOCALE_LABEL_KEYS = {
    "zh-TW": "lang.zh_tw",
    "en": "lang.en",
  };
  function localeLabelKey(locale) {
    return LOCALE_LABEL_KEYS[locale] || ("lang." + locale);
  }
  const options = (typeof i18nLocales === "function" ? i18nLocales() : ["zh-TW", "en"]).map((locale) => {
    const label = (typeof t === "function" ? t(localeLabelKey(locale)) : locale);
    const opt = document.createElement("option");
    opt.value = locale;
    opt.textContent = label;
    return opt;
  });
  localeSelect.replaceChildren(...options);
  if (typeof i18nCurrentLocale === "function") localeSelect.value = i18nCurrentLocale();
}

const localeSelectEl = document.getElementById("locale");
if (localeSelectEl && localeSelectEl.tagName === "SELECT") {
  fillLocaleOptions();
  localeSelectEl.addEventListener("change", () => {
    if (typeof i18nSwitch === "function") i18nSwitch(localeSelectEl.value);
    fillLocaleOptions();
  });
}

/* ====== Print Dialog - 使用實際 print_dialog.js ====== */
if (typeof api === "function" && typeof printDialogApi === "undefined") {
  printDialogApi = {
    get: (path) => api("/api" + path),
    post: (path, body) =>
      api("/api" + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
  };
}

if (document.getElementById("sc-print-btn")) {
  document.getElementById("sc-print-btn").addEventListener("click", async () => {
    try {
      // localized comment
      await printOpenDialog("ITM-10000");
    } catch (e) {
      // Even if API fails, dialog opened via printOpenDialog
      const dialog = document.getElementById("print-dialog");
      if (dialog) dialog.hidden = false;
    }
  });
}

/* ====== Print close ====== */
if (document.getElementById("print-close")) {
  document.getElementById("print-close").addEventListener("click", () => {
    if (typeof printCloseDialog === "function") printCloseDialog();
  });
}

/* ====== Bind when DOM ready ====== */
document.addEventListener("DOMContentLoaded", () => {
  if (typeof i18nSubscribe === "function") {
    i18nSubscribe(() => {
      fillLocaleOptions();
    });
  }
  if (typeof printBind === "function") {
    printBind();
  }
  // localized comment
  fillLocaleOptions();
  // Overlay management
  function updateOverlay() {
    const overlay = document.getElementById("dialog-overlay");
    if (!overlay) return;
    const open = !!(document.getElementById("print-dialog") && !document.getElementById("print-dialog").hidden) ||
                 !!(document.getElementById("sc-confirm") && !document.getElementById("sc-confirm").hidden) ||
                 !!(document.getElementById("sc-error-dialog") && !document.getElementById("sc-error-dialog").hidden);
    overlay.hidden = !open;
  }
  const observer = new MutationObserver(updateOverlay);
  ["print-dialog", "sc-confirm", "sc-error-dialog"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) observer.observe(el, { attributes: true, attributeFilter: ["hidden"] });
  });
  updateOverlay();
});
