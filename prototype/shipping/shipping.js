const MAX_ROWS = 3;

const COMMON = [
  "i5-12400F", "i5-12600KF", "i7-13700K", "i7-14700K",
  "R5 5600X", "R5 7600X", "R7 7800X3D", "R9 7950X",
  "RTX 3060 12G", "RTX 3070", "RTX 4070 Ti SUPER", "RTX 4080 SUPER",
  "B650 主機板", "X670E 主機板", "Z790 主機板",
  "DDR5 6000 32G", "DDR5 6000 16G",
  "SN770 1TB", "990 PRO 1TB", "PM961 256G",
  "Arctic P12 MAX", "PA120",
];

const $ = (sel) => document.querySelector(sel);

document.addEventListener("DOMContentLoaded", init);

function init() {
  const params = new URLSearchParams(location.search);
  const today = new Date();

  $("#f-date").value = params.get("d") || localISO(today);
  $("#f-items").value = (params.get("i") || "").split("|").filter(Boolean).join("\n");
  if (params.get("x")) $("#f-extra").value = params.get("x");
  if (params.get("n")) $("#f-serial").value = params.get("n");
  if (params.get("c")) $("#f-code").value = params.get("c");

  $("#f-date").oninput = render;
  $("#f-items").oninput = render;
  $("#f-extra").oninput = render;
  $("#f-serial").oninput = render;
  $("#f-code").oninput = render;
  $("#print").onclick = () => window.print();

  document.querySelectorAll("[data-zoom]").forEach((btn) => {
    btn.onclick = () => {
      const k = Number(btn.dataset.zoom);
      const w = getComputedStyle(document.body).getPropertyValue("--card-w").trim();
      const h = getComputedStyle(document.body).getPropertyValue("--card-h").trim();
      $("#zoombox").style.width = `calc(${w} * ${k})`;
      $("#zoombox").style.height = `calc(${h} * ${k})`;
      $("#card").style.transform = `scale(${k})`;
      document.querySelectorAll("[data-zoom]").forEach((b) => b.classList.toggle("on", b === btn));
    };
  });

  document.querySelectorAll("[data-size]").forEach((btn) => {
    btn.onclick = () => {
      setSize(btn.dataset.size);
      document.querySelectorAll("[data-size]").forEach((b) => b.classList.toggle("on", b === btn));
      try { localStorage.setItem("slip-size", btn.dataset.size); } catch {}
    };
  });

  let saved = params.get("s") || "4x6";
  if (!params.get("s")) {
    try { saved = localStorage.getItem("slip-size") || "4x6"; } catch {}
  }
  setSize(saved);
  document.querySelectorAll("[data-size]").forEach((b) => b.classList.toggle("on", b.dataset.size === saved));

  const chips = $("#chips");
  COMMON.forEach((name) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.textContent = name;
    btn.onclick = () => {
      const box = $("#f-items");
      const lines = box.value.split("\n").filter((l) => l.trim());
      if (lines.length >= MAX_ROWS) return;
      lines.push(name);
      box.value = lines.join("\n");
      render();
    };
    chips.appendChild(btn);
  });

  render();
}

function render() {
  const iso = $("#f-date").value;
  $("#out-date").textContent = iso ? formatDate(iso) : "—";

  const lines = $("#f-items").value
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .slice(0, MAX_ROWS);

  const list = $("#out-items");
  const rows = [];
  for (let i = 0; i < MAX_ROWS; i++) {
    const text = lines[i] || "";
    rows.push(
      text
        ? `<div class="goods-row"><span class="idx">${i + 1}.</span><span class="txt">${escape(text)}</span></div>`
        : '<div class="goods-row"><span class="idx"></span><span class="txt"></span></div>'
    );
  }
  list.innerHTML = rows.join("");

  $("#out-extra").textContent = $("#f-extra").value.trim();
  setMeta("#out-serial", "序號：", $("#f-serial").value.trim());
  setMeta("#out-code", "編號：", $("#f-code").value.trim());
}

function setMeta(sel, label, value) {
  const el = $(sel);
  el.innerHTML = value ? `<span class="lbl">${label}</span>${escape(value)}` : "";
}

function setSize(key) {
  const map = {
    "4x6": { w: "101.6mm", h: "152.4mm", label: "4 × 6 吋（101.6 × 152.4 mm）" },
    "100x150": { w: "100mm", h: "150mm", label: "100 × 150 mm（原稿尺寸）" },
  };
  const size = map[key] || map["4x6"];
  document.body.dataset.size = key;
  document.getElementById("page-size").textContent = `@page { size: ${size.w} ${size.h}; margin: 0; }`;
  document.getElementById("size-label").textContent = `實際尺寸 ${size.label}`;
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${y}/${m}/${d}`;
}

function localISO(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

function escape(text) {
  return String(text).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
