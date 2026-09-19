"use strict";

// Photos whose longer side exceeds this are downscaled before upload. The VLMs
// downscale large images anyway, and it keeps phone photos under the size limit.
const MAX_EDGE_PX = 2048;
// Larger JPEG/PNG files are re-encoded too, to stay clear of the server's 5 MB default.
const MAX_PASSTHROUGH_BYTES = 4 * 1024 * 1024;
const JPEG_QUALITY = 0.9;
const HISTORY_LIMIT = 20;
const EXTENSIONS = { "image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"] };
const MACROS = [
  { key: "protein", label: "Protein", field: "protein_g", kcalPerGram: 4 },
  { key: "carbs", label: "Carbs", field: "carbs_g", kcalPerGram: 4 },
  { key: "fat", label: "Fat", field: "fat_g", kcalPerGram: 9 },
];
const BANNERS = {
  partial: {
    tone: "warning",
    icon: "alert",
    title: "Partial result",
    text: "Some ingredients couldn't be matched to nutrition data, so the totals leave them out.",
  },
  unknown_meal: {
    tone: "neutral",
    icon: "help",
    title: "No meal recognized",
    text: "No food could be identified in this photo. A clear, well-lit shot where the food fills most of the frame works best.",
  },
  provider_failure: {
    tone: "critical",
    icon: "error",
    title: "Ingredients couldn't be identified",
    text: "The AI provider returned an error, so this isn't necessarily a problem with your photo. Try again in a moment; the details below say what went wrong.",
  },
};
// src/core/analyzer.py reports VLM failures as "unknown_meal" with a warning that starts like this.
const PROVIDER_FAILURE_PREFIX = "ingredient identification failed";
const SVG_NS = "http://www.w3.org/2000/svg";

const $ = (id) => document.getElementById(id);

const el = {
  pillAnalyzer: $("pill-analyzer"),
  pillHistory: $("pill-history"),
  fileInput: $("file-input"),
  dropzone: $("dropzone"),
  preview: $("preview"),
  fileMeta: $("file-meta"),
  uploadNotice: $("upload-notice"),
  serviceNotice: $("service-notice"),
  analyzeButton: $("analyze-btn"),
  resultsCard: $("results-card"),
  resultsSource: $("results-source"),
  views: {
    empty: $("view-empty"),
    loading: $("view-loading"),
    error: $("view-error"),
    result: $("view-result"),
  },
  elapsed: $("loading-elapsed"),
  errorText: $("error-text"),
  retryButton: $("retry-btn"),
  resultBanner: $("result-banner"),
  nutrition: $("result-nutrition"),
  totalKcal: $("total-kcal"),
  macroSplit: $("macro-split"),
  macroBar: $("macro-bar"),
  ingredientsBody: $("ingredients-body"),
  details: $("result-details"),
  warnings: $("warnings"),
  rawJson: $("raw-json"),
  historyList: $("history-list"),
  historyNote: $("history-note"),
  historyRefresh: $("history-refresh"),
  srStatus: $("sr-status"),
};

const state = {
  upload: null, // { file, previewUrl, sourceName, sourceSize, width, height, note }
  busy: false,
  analyzerReady: true,
  historyEnabled: true,
  shownId: null,
  selection: 0, // lets a newer file selection win over a slower, older one
};

// ---- Formatting ----

const fmt0 = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const fmt1 = new Intl.NumberFormat("en", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });
const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

function formatBytes(bytes) {
  return bytes < 1024 * 1024 ? `${fmt0.format(bytes / 1024)} KB` : `${fmt1.format(bytes / 1024 / 1024)} MB`;
}

function timeAgo(date) {
  const seconds = (date.getTime() - Date.now()) / 1000;
  const age = Math.abs(seconds);
  if (age < 60) return "just now";
  if (age < 3600) return relative.format(Math.round(seconds / 60), "minute");
  if (age < 86400) return relative.format(Math.round(seconds / 3600), "hour");
  if (age < 7 * 86400) return relative.format(Math.round(seconds / 86400), "day");
  return dateTime.format(date);
}

const basename = (path) => path.split(/[\\/]/).pop() || path;
const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

// Whole percentages that add up to exactly 100 (largest-remainder rounding).
function percentages(values) {
  const total = values.reduce((sum, value) => sum + value, 0);
  if (!(total > 0)) return null;
  const exact = values.map((value) => (value / total) * 100);
  const result = exact.map((value) => Math.floor(value));
  let left = 100 - result.reduce((sum, value) => sum + value, 0);
  const byRemainder = exact.map((_, i) => i).sort((a, b) => (exact[b] - result[b]) - (exact[a] - result[a]));
  for (const i of byRemainder) {
    if (left <= 0) break;
    result[i] += 1;
    left -= 1;
  }
  return result;
}

// ---- DOM helpers ----

// Strings become text nodes, never HTML: ingredient names come from the VLM
// and filenames from users.
function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name === "text") node.textContent = value;
    else node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
}

function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function showNotice(node, message) {
  node.textContent = message;
  node.hidden = !message;
}

function announce(message) {
  el.srStatus.textContent = message;
}

// ---- Server calls ----

// Returns the parsed JSON body, or throws an Error whose message can be shown as-is.
async function requestJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { cache: "no-store", ...options });
  } catch {
    throw new Error("Couldn't reach the server. Check that it's still running, then try again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(describeFailure(response.status, body));
  if (body === null) throw new Error("The server's response wasn't valid JSON.");
  return body;
}

function describeFailure(status, body) {
  const detail = typeof body?.detail === "string" ? body.detail : "";
  if (status === 400) return detail || "The server couldn't read this image.";
  if (status === 503) return detail || "The service is unavailable right now.";
  if (status === 422) return "The server rejected the request as incomplete (HTTP 422).";
  return `The server hit an unexpected error (HTTP ${status}). Check the server logs, then try again.`;
}

async function checkHealth() {
  let health;
  try {
    health = await requestJson("health");
  } catch {
    setPill(el.pillAnalyzer, "critical", "Server unreachable");
    setPill(el.pillHistory, "neutral", "History unknown");
    return;
  }
  state.analyzerReady = health.analyzer === "ready";
  state.historyEnabled = health.database !== "unavailable";
  setPill(el.pillAnalyzer, state.analyzerReady ? "good" : "critical",
    state.analyzerReady ? "Analyzer ready" : "Analyzer unavailable");
  setPill(el.pillHistory, state.historyEnabled ? "good" : "warning",
    state.historyEnabled ? "History on" : "History off");
  showNotice(el.serviceNotice, state.analyzerReady ? ""
    : "Analysis is unavailable: the server's analyzer isn't configured. Check the API keys in the server's .env file, then restart it.");
  updateAnalyzeButton();
}

function setPill(pill, tone, label) {
  pill.dataset.tone = tone;
  pill.querySelector(".pill-label").textContent = label;
}

// ---- Choosing a photo ----

async function selectFile(file) {
  if (!file || state.busy) return;
  const selection = ++state.selection;
  showNotice(el.uploadNotice, "");
  const previewUrl = URL.createObjectURL(file);
  let image;
  let prepared;
  try {
    image = await loadImage(previewUrl, file.name);
    prepared = await prepareUpload(file, image);
  } catch (error) {
    URL.revokeObjectURL(previewUrl);
    if (selection === state.selection) showNotice(el.uploadNotice, error.message);
    return;
  }
  if (selection !== state.selection) {
    URL.revokeObjectURL(previewUrl);
    return;
  }
  setUpload({
    ...prepared,
    previewUrl,
    sourceName: file.name,
    sourceSize: file.size,
    width: image.naturalWidth,
    height: image.naturalHeight,
  });
}

async function loadImage(url, name) {
  const image = new Image();
  image.src = url;
  try {
    await image.decode();
  } catch {
    // Checked below: a file the browser can't decode has no natural size.
  }
  if (!image.naturalWidth || !image.naturalHeight) {
    throw new Error(`"${name}" isn't an image this browser can open. Please choose a JPEG or PNG photo.`);
  }
  return image;
}

// Returns the file to upload: the original when the server accepts it as-is,
// otherwise a JPEG re-encode (other formats, or too large in pixels or bytes).
async function prepareUpload(file, image) {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  const type = await sniffType(file);
  const scale = Math.min(1, MAX_EDGE_PX / Math.max(width, height));
  if (type && scale === 1 && file.size <= MAX_PASSTHROUGH_BYTES) {
    const name = withExtension(file.name, type);
    return { file: new File([file], name, { type }), note: name === file.name ? "" : `Uploads as ${name}` };
  }

  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context.fillStyle = "#fff"; // JPEG has no transparency
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingQuality = "high";
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
  if (!blob) throw new Error("This image couldn't be converted for upload. Please choose a JPEG or PNG photo.");
  const action = scale < 1 ? `Resized to ${canvas.width} × ${canvas.height}`
    : type === "image/jpeg" ? "Compressed" : "Converted to JPEG";
  return {
    file: new File([blob], withExtension(file.name, "image/jpeg"), { type: "image/jpeg" }),
    note: `${action} for upload (${formatBytes(blob.size)})`,
  };
}

// Reads the magic bytes: file.type only reflects the file's extension.
async function sniffType(file) {
  const b = new Uint8Array(await file.slice(0, 4).arrayBuffer());
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return "image/png";
  return null;
}

// The server rejects a filename whose extension doesn't match the format (e.g. photo.jfif).
function withExtension(name, type) {
  const extensions = EXTENSIONS[type];
  if (extensions.some((ext) => name.toLowerCase().endsWith(ext))) return name;
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name || "photo";
  return stem + extensions[0];
}

function setUpload(upload) {
  if (state.upload) URL.revokeObjectURL(state.upload.previewUrl);
  state.upload = upload;
  el.preview.src = upload.previewUrl;
  el.preview.alt = `Selected photo: ${upload.sourceName}`;
  el.preview.hidden = false;
  el.dropzone.classList.add("has-image");
  el.fileMeta.replaceChildren(
    h("span", { class: "file-name", text: upload.sourceName }),
    h("span", { text: `${formatBytes(upload.sourceSize)} · ${upload.width} × ${upload.height}` }),
    ...(upload.note ? [h("span", { class: "file-note", text: upload.note })] : []),
  );
  el.fileMeta.hidden = false;
  updateAnalyzeButton();
}

// ---- Analysis ----

async function analyze() {
  if (!state.upload || state.busy) return;
  setBusy(true);
  showNotice(el.uploadNotice, ""); // a message about an earlier rejected file is stale now
  el.resultsSource.hidden = true;
  showView("loading");
  revealResults();
  announce("Analyzing your meal…");

  const started = Date.now();
  const tick = () => {
    el.elapsed.textContent = `${Math.floor((Date.now() - started) / 1000)} s elapsed`;
  };
  tick();
  const timer = setInterval(tick, 1000);

  const form = new FormData();
  form.append("file", state.upload.file);
  try {
    const record = await requestJson("analyze", { method: "POST", body: form });
    showRecord(record);
    announce(record.status === "unknown_meal"
      ? "Analysis complete: no meal recognized."
      : `Analysis complete: ${fmt0.format(record.totals.kcal)} kcal from ${plural(record.ingredients.length, "ingredient")}.`);
    loadHistory();
  } catch (error) {
    el.errorText.textContent = error.message;
    showView("error");
    announce(`Analysis failed. ${error.message}`);
  } finally {
    clearInterval(timer);
    setBusy(false);
  }
}

function setBusy(busy) {
  state.busy = busy;
  el.analyzeButton.classList.toggle("is-busy", busy);
  el.analyzeButton.querySelector(".btn-label").textContent = busy ? "Analyzing…" : "Analyze meal";
  el.fileInput.disabled = busy;
  el.dropzone.classList.toggle("is-disabled", busy);
  el.historyList.inert = busy;
  el.resultsCard.setAttribute("aria-busy", String(busy));
  updateAnalyzeButton();
}

function updateAnalyzeButton() {
  el.analyzeButton.disabled = state.busy || !state.upload || !state.analyzerReady;
}

function showView(name) {
  for (const [key, view] of Object.entries(el.views)) view.hidden = key !== name;
}

// On narrow screens the results card sits below the others, so bring it into view.
function revealResults() {
  const top = el.resultsCard.getBoundingClientRect().top;
  if (top >= 0 && top <= window.innerHeight * 0.6) return;
  const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.resultsCard.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
}

// ---- Rendering an analysis record ----

function showRecord(record) {
  state.shownId = record.id;
  el.resultsSource.replaceChildren(
    h("span", { class: "results-file", title: record.image_filename, text: basename(record.image_filename) }),
    ` · analyzed ${dateTime.format(new Date(record.created_at))}`,
  );
  el.resultsSource.hidden = false;

  const providerFailed = record.warnings.some((warning) => warning.startsWith(PROVIDER_FAILURE_PREFIX));
  const banner = providerFailed ? BANNERS.provider_failure : BANNERS[record.status];
  el.resultBanner.hidden = !banner;
  if (banner) {
    el.resultBanner.dataset.tone = banner.tone;
    el.resultBanner.replaceChildren(
      icon(banner.icon),
      h("div", {},
        h("p", { class: "banner-title", text: banner.title }),
        h("p", { class: "banner-text", text: banner.text })),
    );
  }

  const recognized = record.status !== "unknown_meal";
  el.nutrition.hidden = !recognized;
  if (recognized) {
    renderTotals(record.totals);
    renderIngredients(record.ingredients, record.totals);
  }

  el.warnings.replaceChildren(...record.warnings.map((text) => h("li", {}, icon("alert"), h("span", { text }))));
  el.details.hidden = record.warnings.length === 0;
  el.rawJson.textContent = JSON.stringify(record, null, 2);
  showView("result");
  markShownHistoryItem();
}

function renderTotals(totals) {
  el.totalKcal.textContent = fmt0.format(totals.kcal);
  const energy = MACROS.map((macro) => Math.max(0, totals[macro.field]) * macro.kcalPerGram);
  const shares = percentages(energy);
  const segments = [];
  MACROS.forEach((macro, i) => {
    const grams = `${fmt1.format(totals[macro.field])} g`;
    $(`total-${macro.key}`).textContent = grams;
    $(`share-${macro.key}`).textContent = shares ? `${shares[i]}% of kcal` : "";
    if (!shares || energy[i] === 0) return;
    const segment = h("span", {
      class: "segment",
      "data-macro": macro.key,
      tabindex: "0",
      role: "img",
      "aria-label": `${macro.label}: ${shares[i]}% of calories, ${grams}`,
    }, h("span", { class: "tooltip", "aria-hidden": "true" },
      h("strong", { text: `${shares[i]}%` }), ` ${macro.label} · ${grams}`));
    segment.style.flexGrow = String(energy[i]);
    segments.push(segment);
  });
  el.macroBar.replaceChildren(...segments);
  el.macroSplit.hidden = segments.length === 0;
}

function renderIngredients(ingredients, totals) {
  el.ingredientsBody.replaceChildren(...ingredients.map((item) => {
    const n = item.nutrition;
    const name = h("th", { scope: "row" }, item.name);
    if (!n) name.append(h("span", { class: "missing-tag", text: "no nutrition data" }));
    const values = n
      ? [fmt0.format(n.kcal), fmt1.format(n.protein_g), fmt1.format(n.carbs_g), fmt1.format(n.fat_g)]
      : ["–", "–", "–", "–"];
    return h("tr", n ? {} : { class: "is-missing" },
      name,
      h("td", { class: "num", text: fmt0.format(item.estimated_grams) }),
      ...values.map((text) => h("td", { class: "num", text })),
      h("td", { class: "num", text: `${fmt0.format(item.confidence * 100)}%` }),
    );
  }));
  $("foot-grams").textContent = fmt0.format(ingredients.reduce((sum, item) => sum + item.estimated_grams, 0));
  $("foot-kcal").textContent = fmt0.format(totals.kcal);
  $("foot-protein").textContent = fmt1.format(totals.protein_g);
  $("foot-carbs").textContent = fmt1.format(totals.carbs_g);
  $("foot-fat").textContent = fmt1.format(totals.fat_g);
}

// ---- History ----

async function loadHistory() {
  if (!state.historyEnabled) {
    el.historyList.replaceChildren();
    el.historyNote.textContent = "History is off because the server has no database connection.";
    return;
  }
  let records;
  try {
    records = await requestJson(`analyses?limit=${HISTORY_LIMIT}`);
  } catch (error) {
    // Keep showing the previous list; just explain why it didn't refresh.
    el.historyNote.textContent = `Couldn't load history. ${error.message}`;
    return;
  }
  renderHistory(records);
}

function renderHistory(records) {
  el.historyList.replaceChildren(...records.map((record) => {
    const created = new Date(record.created_at);
    const recognized = record.status !== "unknown_meal";
    const kcal = h("span", { class: recognized ? "history-kcal" : "history-kcal is-muted" });
    if (record.status === "partial") {
      kcal.title = "Partial result: some ingredients have no nutrition data";
      kcal.append(icon("alert"), h("span", { class: "visually-hidden", text: "Partial result:" }));
    }
    kcal.append(recognized ? `${fmt0.format(record.totals.kcal)} kcal` : "No meal");

    const button = h("button", { type: "button", class: "history-item", "data-id": record.id },
      h("span", { class: "history-main" },
        h("span", { class: "history-name", title: record.image_filename, text: basename(record.image_filename) }),
        h("span", { class: "history-meta" },
          h("time", { datetime: record.created_at, title: dateTime.format(created), text: timeAgo(created) }),
          recognized ? ` · ${plural(record.ingredients.length, "ingredient")}` : ""),
      ),
      kcal,
    );
    button.addEventListener("click", () => {
      showRecord(record);
      revealResults();
    });
    return h("li", {}, button);
  }));
  el.historyNote.textContent = records.length ? "" : "No analyses yet. Your results will be listed here.";
  markShownHistoryItem();
}

function markShownHistoryItem() {
  for (const button of el.historyList.querySelectorAll(".history-item")) {
    if (button.dataset.id === state.shownId) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }
}

// ---- Wiring ----

el.fileInput.addEventListener("change", () => {
  const [file] = el.fileInput.files;
  el.fileInput.value = ""; // so picking the same file again still fires "change"
  selectFile(file);
});

const hasFiles = (event) => Array.from(event.dataTransfer?.types ?? []).includes("Files");
let dragDepth = 0;

window.addEventListener("dragenter", (event) => {
  if (!hasFiles(event)) return;
  dragDepth += 1;
  el.dropzone.classList.add("is-dragging");
});

window.addEventListener("dragleave", (event) => {
  if (!hasFiles(event)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) el.dropzone.classList.remove("is-dragging");
});

// Accept a drop anywhere on the page, instead of the browser opening the file.
window.addEventListener("dragover", (event) => {
  if (!hasFiles(event)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = state.busy ? "none" : "copy";
});

window.addEventListener("drop", (event) => {
  if (!hasFiles(event)) return;
  event.preventDefault();
  dragDepth = 0;
  el.dropzone.classList.remove("is-dragging");
  selectFile(event.dataTransfer.files[0]);
});

document.addEventListener("paste", (event) => {
  const file = Array.from(event.clipboardData?.files ?? []).find((item) => item.type.startsWith("image/"));
  if (!file) return;
  event.preventDefault();
  selectFile(file);
});

el.analyzeButton.addEventListener("click", analyze);
el.retryButton.addEventListener("click", analyze);
el.historyRefresh.addEventListener("click", loadHistory);

checkHealth().then(loadHistory);
