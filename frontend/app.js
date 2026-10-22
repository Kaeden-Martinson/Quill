const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const state = {
  token: null,
  draftId: null,
  lastSaved: "",
  openVersion: null,
  suggestions: [], // {id, original, revised, reason, category, card}
  run: null,       // AbortController for the review in progress
  current: null,   // the note picked with the keyboard
  aiText: null,    // Quill's AI draft of this essay, if it started as one
  aiCache: new Map(),
  profile: null,
  voices: null,    // presets and custom settings, from the server
  ignored: [],
};
let nextId = 1;

// ---------- small helpers ----------

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value);
  } catch { return null; }
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c != null));
  return node;
}

const SVG = "http://www.w3.org/2000/svg";
function icon(name) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `#${name}`);
  svg.append(use);
  return svg;
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  el("a", { href: url, download: filename }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const fmtDate = (ts) => new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { timeStyle: "short" });
const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");

// ---------- network ----------

async function request(path, options = {}) {
  const isJson = options.body && !(options.body instanceof ArrayBuffer) && typeof options.body !== "string";
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": isJson ? "application/json" : "application/octet-stream",
      Authorization: `Bearer ${state.token || ""}`,
      ...(options.headers || {}),
    },
    body: isJson ? JSON.stringify(options.body) : options.body,
  });
  if (res.status === 401 && !["/api/login", "/api/register"].includes(path)) { signOut(); throw new Error("Please sign in"); }
  if (!res.ok) {
    const { detail } = await res.json().catch(() => ({}));
    // Validation errors arrive as a list, e.g. a password that's too short.
    const message = Array.isArray(detail) ? detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ") : detail;
    throw new Error(message || `Request failed (${res.status})`);
  }
  return res;
}

async function api(path, options = {}) {
  const res = await request(path, options);
  return res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
}

// Reads a newline-delimited JSON stream, calling onEvent for each object as it arrives.
async function stream(path, body, onEvent, signal) {
  const res = await request(path, { method: "POST", body, signal });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    lines.filter(Boolean).forEach((line) => onEvent(JSON.parse(line)));
  }
}

// ---------- theme ----------

function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function renderThemeButton() {
  const dark = currentTheme() === "dark";
  const btn = $("#theme-toggle");
  const svg = icon(dark ? "i-sun" : "i-moon");
  svg.classList.add("swap");
  btn.replaceChildren(svg);
  btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  btn.title = dark ? "Light mode" : "Dark mode";
}

$("#theme-toggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  // Switch every color at once instead of letting hover transitions fade some of them.
  const root = document.documentElement;
  root.classList.add("theme-switching");
  root.dataset.theme = next;
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switching")));
  storage("quill-theme", next);
  renderThemeButton();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderThemeButton);
renderThemeButton();

// ---------- auth ----------

function showApp() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  setView("write");
  refreshStatus();
  // A stale token fails here; request() already sends the user back to sign in.
  loadDrafts().catch(() => {});
  loadProfile().catch(() => {});
  loadIgnored().catch(() => {});
  api("/api/me").then(({ name }) => {
    $("#account-name").textContent = name;
    $("#account-username").value = name;
    $("#menu-name").textContent = name;
    $("#avatar-initial").textContent = name.trim().charAt(0).toUpperCase();
  }).catch(() => {});
}

function signOut() {
  state.token = null;
  storage("quill-token", null);
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
}

let registering = false;
$("#toggle-mode").addEventListener("click", () => {
  registering = !registering;
  const form = $("#login-form");
  $("#invite-field").hidden = !registering;
  form.invite.required = registering;
  form.password.autocomplete = registering ? "new-password" : "current-password";
  form.password.minLength = registering ? 8 : 0;
  $("#login-heading").textContent = registering ? "Create your account" : "Sign in";
  $("#login-submit").textContent = registering ? "Create account" : "Sign in";
  $("#mode-hint").textContent = registering ? "Already have an account?" : "New here?";
  $("#toggle-mode").textContent = registering ? "Sign in" : "Create an account";
  $("#login-error").textContent = "";
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const submit = $("#login-submit");
  submit.disabled = true;
  try {
    const { token } = await api(registering ? "/api/register" : "/api/login", {
      method: "POST",
      body: { name: form.get("name"), password: form.get("password"), invite: form.get("invite") },
    });
    state.token = token;
    storage("quill-token", token);
    $("#login-error").textContent = "";
    showApp();
  } catch (err) {
    $("#login-error").textContent = err.message;
  } finally {
    submit.disabled = false;
  }
});

async function logout() {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  signOut();
}
$("#logout").addEventListener("click", logout);

async function refreshStatus() {
  const status = $("#model-status");
  try {
    const s = await api("/api/status");
    status.className = `status ${s.model_ready ? "ready" : "down"}`;
    status.title = s.model_ready ? `Model ${s.model} is ready` : `Model ${s.model} is offline`;
    status.querySelector(".status-text").textContent = s.model_ready ? "Ready" : "Offline";
  } catch {
    status.className = "status down";
    status.querySelector(".status-text").textContent = "Server unreachable";
  }
}

// ---------- views, drawer, tabs ----------

function setView(view) {
  const changed = $(`#${view}-view`).hidden;
  $("#write-view").hidden = view !== "write";
  $("#voice-view").hidden = view !== "voice";
  $("#app-view").classList.toggle("voice-mode", view === "voice");
  $$(".view-tab").forEach((b) => (b.dataset.view === view ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  // The account menu offers whichever page you're not on.
  $$("#account-menu [data-view]").forEach((b) => { b.hidden = b.dataset.view === view; });
  updateCrumb();
  closeDrawer();
  closeMenu();
  if (changed) window.scrollTo({ top: 0 });
  if (view === "write") requestAnimationFrame(() => { placeNotes(); moveTabIndicator(); });
}

$$("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
$("#home").addEventListener("click", () => setView("write"));

// The bar gets a hairline once the page scrolls under it.
addEventListener("scroll", () => $("#bar").classList.toggle("scrolled", scrollY > 4), { passive: true });

// ---------- account menu ----------

function toggleMenu(open = !$(".account").classList.contains("open")) {
  $(".account").classList.toggle("open", open);
  $("#account-btn").setAttribute("aria-expanded", open);
  if (open) $("#account-menu [role=menuitem]:not([hidden])").focus();
}
const closeMenu = () => {
  if ($(".account").classList.contains("open")) toggleMenu(false);
};
$("#account-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(); });
document.addEventListener("click", (e) => { if (!e.target.closest(".account")) closeMenu(); });
$("#account-menu").addEventListener("keydown", (e) => {
  const items = $$("#account-menu [role=menuitem]").filter((b) => !b.hidden);
  const i = items.indexOf(document.activeElement);
  const next = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: items.length - 1 }[e.key];
  if (e.key === "Escape") { e.preventDefault(); toggleMenu(false); $("#account-btn").focus(); return; }
  if (e.key === "Tab") { toggleMenu(false); return; }
  if (next === undefined) return;
  e.preventDefault();
  items[(next + items.length) % items.length].focus();
});

let drawerOpener = null;

function toggleDrawer(open = !$("#app-view").classList.contains("drawer-open")) {
  const overlay = open;
  const wasOpen = $("#app-view").classList.contains("drawer-open");
  $("#app-view").classList.toggle("drawer-open", overlay);
  $("#scrim").hidden = !overlay;
  // While the drawer covers the page, everything behind it is inert: keyboard and screen-reader
  // focus stay inside the drawer instead of wandering into content you can't see.
  $(".main").inert = overlay;
  $("#open-drawer").setAttribute("aria-expanded", overlay);
  if (overlay && !wasOpen) {
    drawerOpener = document.activeElement;
    $("#draft-filter").value = "";
    renderDraftList();
    $("#draft-filter").focus();
  } else if (!overlay && wasOpen) {
    if (drawerOpener?.isConnected && !drawerOpener.closest("[inert]")) drawerOpener.focus();
    drawerOpener = null;
  }
}
const closeDrawer = () => toggleDrawer(false);
$("#open-drawer").addEventListener("click", () => toggleDrawer());
$("#close-drawer").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);

function setTab(name) {
  $$(".tab").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1; // one tab stop for the whole tab list; arrows move within it
  });
  $$(".panel").forEach((p) => { p.hidden = p.dataset.panel !== name; });
  moveTabIndicator();
  if (name === "edits") requestAnimationFrame(placeNotes); // positions need the panel visible
  if (name === "report") renderReport();
}
$$(".tab").forEach((t) => t.addEventListener("click", () => setTab(t.dataset.tab)));

function moveTabIndicator() {
  const tab = $(".tab.active");
  const ind = $(".tab-ind");
  if (!tab || !tab.offsetWidth) return;
  ind.style.width = `${tab.offsetWidth}px`;
  ind.style.transform = `translateX(${tab.offsetLeft}px)`;
}
addEventListener("resize", moveTabIndicator);

// Arrow keys, Home and End move between tabs (the standard keyboard pattern for tab lists).
$(".tabs").addEventListener("keydown", (e) => {
  const tabs = $$(".tab");
  const i = tabs.indexOf(document.activeElement);
  if (i === -1) return;
  const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (next === undefined) return;
  e.preventDefault();
  const tab = tabs[(next + tabs.length) % tabs.length];
  setTab(tab.dataset.tab);
  tab.focus();
});

function updateCrumb() {
  $("#crumb-title").textContent = state.draftId ? $("#title").value.trim() || "Untitled essay" : "No essay open";
}

function setDraftControls(enabled) {
  for (const id of ["#review", "#review-phone", "#overview", "#save", "#replay", "#export", "#export-docx", "#delete-draft"]) $(id).disabled = !enabled;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeDrawer(); closeMenu(); }
  // Ctrl+K (Cmd+K on a Mac) opens the essay switcher from anywhere.
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && !$("#app-view").hidden) {
    e.preventDefault();
    toggleDrawer();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && state.draftId) {
    e.preventDefault();
    saveVersion("Manual save");
  }
  // Working through notes from the keyboard, without leaving the text.
  if (e.altKey && !e.ctrlKey && !e.metaKey && !$("#write-view").hidden && state.suggestions.length) {
    const action = { ArrowDown: () => moveCurrent(1), ArrowUp: () => moveCurrent(-1),
      Enter: () => actOnCurrent(true), Backspace: () => actOnCurrent(false) }[e.key];
    if (action) { e.preventDefault(); action(); }
  }
});

// ---------- Write / Mark-up ----------

function setMode(mode) {
  $("#app-view").classList.toggle("write-mode", mode === "write");
  $$(".mode button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
  storage("quill-mode", mode);
  renderMarkup();
}
const writeMode = () => $("#app-view").classList.contains("write-mode");
$$(".mode button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

// ---------- drafts ----------

let drafts = [];

async function loadDrafts() {
  drafts = await api("/api/drafts");
  renderDraftList();
}

// The essay list, narrowed by the search box. Arrow keys move through it from the search box.
function renderDraftList() {
  const q = $("#draft-filter").value.trim().toLowerCase();
  const shown = drafts.filter((d) => d.title.toLowerCase().includes(q));
  $("#draft-list").replaceChildren(
    ...(shown.length
      ? shown.map((d) =>
          el("li", {},
            el("button", { class: d.id === state.draftId ? "active" : "", "aria-current": d.id === state.draftId ? "true" : "false", onclick: () => openDraft(d.id) },
              el("span", { class: "d-title" }, d.title),
              el("span", { class: "d-meta" }, `${d.versions} version${d.versions === 1 ? "" : "s"} · ${fmtDate(d.updated)}`))))
      : [el("li", { class: "empty-list" }, drafts.length ? "No essay by that name." : "No essays yet. Start one below.")])
  );
}

$("#draft-filter").addEventListener("input", renderDraftList);
$("#drawer").addEventListener("keydown", (e) => {
  if (!["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) return;
  const items = $$("#draft-list button");
  if (!items.length) return;
  const i = items.indexOf(document.activeElement);
  if (e.key === "Enter") {
    if (document.activeElement === $("#draft-filter")) { e.preventDefault(); items[0].click(); }
    return;
  }
  e.preventDefault();
  if (e.key === "ArrowDown") items[Math.min(items.length - 1, i + 1)].focus();
  else if (i <= 0) $("#draft-filter").focus();
  else items[i - 1].focus();
});

async function newDraft() {
  await saveVersion("Switched essays");
  const { id } = await api("/api/drafts", { method: "POST", body: { title: "Untitled essay" } });
  await openDraft(id);
  $("#title").select();
}

const pickFile = () => $("#import-file").click();
$("#new-draft").addEventListener("click", newDraft);
$("#import-docx").addEventListener("click", pickFile);
$('[data-action="new"]').addEventListener("click", newDraft);
$('[data-action="import"]').addEventListener("click", pickFile);
$$('[data-action="compose"]').forEach((b) => b.addEventListener("click", openCompose));

$("#import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    await saveVersion("Switched essays");
    const { id } = await api("/api/import/docx", { method: "POST", body: await file.arrayBuffer() });
    await openDraft(id);
  } catch (err) {
    alert(err.message);
  }
});

async function openDraft(id) {
  if (state.draftId && state.draftId !== id) await saveVersion("Switched essays");
  stopRun();
  const d = await api(`/api/drafts/${id}`);
  state.draftId = id;
  state.lastSaved = d.body;
  setView("write");
  $("#no-draft").hidden = true;
  $("#draft-area").hidden = false;
  $("#title").value = d.title;
  $("#body").value = d.body;
  for (const field of ["goal", "audience", "tone"]) $(`#${field}`).value = d[field] || "";
  state.aiText = d.ai_text || null;
  state.aiCache = new Map();
  $("#save-status").textContent = "";
  setDraftControls(true);
  renderVersions(d.versions);
  clearFeedback();
  setTab("edits");
  onBodyChange();
  updateCrumb();
  loadDrafts();
}

function renderVersions(versions) {
  $("#version-count").textContent = versions.length || "";
  moveTabIndicator();
  $("#version-list").replaceChildren(
    ...[...versions].reverse().map((v) =>
      el("li", {},
        el("button", { onclick: () => viewVersion(v.id) },
          el("span", { class: "v-note" }, v.note || "Autosave", v.source === "ai" && !/AI/.test(v.note) ? el("span", { class: "tag-ai" }, " · AI-written") : null),
          el("span", { class: "v-meta" }, `${fmtDate(v.created)} · ${v.chars.toLocaleString()} characters`))))
  );
}

async function saveVersion(note = "") {
  if (!state.draftId) return;
  const body = $("#body").value;
  if (body === state.lastSaved) return;
  try {
    await api(`/api/drafts/${state.draftId}/versions`, { method: "POST", body: { body, note } });
    state.lastSaved = body;
    $("#save-status").textContent = `Saved ${fmtTime(Date.now() / 1000)}`;
    const d = await api(`/api/drafts/${state.draftId}`);
    renderVersions(d.versions);
  } catch (err) {
    $("#save-status").textContent = `Not saved: ${err.message}`;
  }
}

// Browsers cancel normal requests when a page closes, and phones often skip unload events
// entirely. Saving whenever the page is hidden, with keepalive, survives tab close, app
// switching, and the phone locking.
function saveOnLeave() {
  if (!state.draftId || !state.token) return;
  const body = $("#body").value;
  if (body === state.lastSaved) return;
  state.lastSaved = body;
  fetch(`/api/drafts/${state.draftId}/versions`, {
    method: "POST",
    keepalive: true,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
    body: JSON.stringify({ body, note: "Autosave" }),
  }).catch(() => { state.lastSaved = ""; });
}

$("#save").addEventListener("click", () => saveVersion(prompt("Name this version (optional)") || "Manual save"));
setInterval(() => saveVersion("Autosave"), 120000);
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState === "hidden") return saveOnLeave();
  // Back on the tab: show the version that was saved while it was hidden.
  if (!state.draftId) return;
  const d = await api(`/api/drafts/${state.draftId}`).catch(() => null);
  if (d) { renderVersions(d.versions); loadDrafts(); }
});
window.addEventListener("pagehide", saveOnLeave);

$("#title").addEventListener("input", updateCrumb);
$("#title").addEventListener("change", async () => {
  const title = $("#title").value.trim() || "Untitled essay";
  await api(`/api/drafts/${state.draftId}`, { method: "PATCH", body: { title } });
  loadDrafts();
});

// Goal, audience and tone are saved with the essay and sent with every review.
$$(".doc-meta [data-field]").forEach((input) => input.addEventListener("change", () => {
  if (!state.draftId) return;
  api(`/api/drafts/${state.draftId}`, { method: "PATCH", body: { [input.dataset.field]: input.value.trim() } })
    .catch((err) => { $("#save-status").textContent = `Not saved: ${err.message}`; });
}));
const goals = () => ({ goal: $("#goal").value, audience: $("#audience").value, tone: $("#tone").value });

async function viewVersion(id) {
  const v = await api(`/api/versions/${id}`);
  state.openVersion = v;
  $("#version-title").textContent = `${v.note || "Autosave"} · ${fmtDate(v.created)}`;
  $("#version-body").textContent = v.body;
  $("#version-dialog").showModal();
}

$("#version-dialog").addEventListener("close", async () => {
  if ($("#version-dialog").returnValue === "restore" && state.openVersion) {
    await saveVersion("Before restoring an older version");
    replaceRange(0, $("#body").value.length, state.openVersion.body); // undoable too
    await saveVersion(`Restored version from ${fmtDate(state.openVersion.created)}`);
  }
});

$("#delete-draft").addEventListener("click", () => {
  $("#delete-title").textContent = $("#title").value.trim() || "Untitled essay";
  $("#delete-versions").textContent = $("#version-count").textContent || "0";
  $("#delete-dialog").returnValue = "";
  $("#delete-dialog").showModal();
});

$("#delete-dialog").addEventListener("close", async () => {
  if ($("#delete-dialog").returnValue !== "delete" || !state.draftId) return;
  const id = state.draftId;
  stopRun();
  try {
    await api(`/api/drafts/${id}`, { method: "DELETE" });
  } catch (err) {
    alert(`Couldn't delete: ${err.message}`);
    return;
  }
  // Forget the essay entirely so no autosave can recreate a version for it.
  state.draftId = null;
  state.lastSaved = "";
  state.aiText = null;
  $("#body").value = "";
  $("#title").value = "";
  $("#draft-area").hidden = true;
  $("#no-draft").hidden = false;
  $("#version-list").replaceChildren();
  $("#version-count").textContent = "";
  setDraftControls(false);
  clearFeedback();
  updateCrumb();
  loadDrafts();
});

$("#export").addEventListener("click", async () => {
  await saveVersion("Before export");
  const text = await api(`/api/drafts/${state.draftId}/history.txt`);
  download(new Blob([text], { type: "text/plain" }), `${$("#title").value || "essay"} - history.txt`);
});

$("#export-docx").addEventListener("click", async () => {
  await saveVersion("Before Word export");
  const res = await request(`/api/drafts/${state.draftId}/export.docx`);
  download(await res.blob(), `${$("#title").value || "essay"}.docx`);
});

// ---------- editor: auto-grow and markup ----------

function onBodyChange() {
  const body = $("#body");
  const words = body.value.trim().split(/\s+/).filter(Boolean).length;
  $("#word-count").textContent = `${words.toLocaleString()} word${words === 1 ? "" : "s"}`;
  // Grow with the content so the textarea never scrolls and stays aligned with the mirror.
  body.style.height = "auto";
  body.style.height = `${body.scrollHeight}px`;
  renderMarkup();
  if (gutter.marks.length) renderGutter();
  if (!$("#panel-report").hidden) scheduleReport();
}
$("#body").addEventListener("input", onBodyChange);
window.addEventListener("resize", onBodyChange);

// Where each live suggestion currently sits in the text (no overlaps).
function suggestionRanges() {
  const text = $("#body").value;
  const ranges = [];
  // Edits with a rewrite claim their text before plain phrase flags inside them.
  const byPriority = [...state.suggestions].sort((a, b) => (a.revised == null) - (b.revised == null));
  for (const s of byPriority) {
    const start = locate(s, text);
    if (start === -1) continue;
    const end = start + s.original.length;
    if (ranges.some((r) => start < r.end && end > r.start)) continue;
    ranges.push({ start, end, s });
  }
  return ranges.sort((a, b) => a.start - b.start);
}

// Replaces a range through the browser's editing command so Ctrl+Z can undo it.
function replaceRange(start, end, text) {
  const body = $("#body");
  body.focus({ preventScroll: true });
  body.setSelectionRange(start, end);
  const ok = document.execCommand("insertText", false, text);
  if (!ok) { // very old browsers: still correct, just not undoable
    body.setRangeText(text, start, end, "end");
    body.dispatchEvent(new Event("input"));
  }
}

// One suggestion drawn as red-pencil markup. Only the words that change are struck through,
// with the replacement written above them; the mirror's text must equal the original exactly.
function markupFor(s, original) {
  if (s.revised == null) return el("span", { class: "mk flag", "data-id": s.id }, original); // stock phrase
  const span = el("span", { class: "mk", "data-id": s.id });
  for (const seg of diffWords(original, s.revised)) {
    if (seg.type === "keep") { span.append(seg.del); continue; }
    const lead = seg.del.match(/^\s*/)[0];
    const core = seg.del.slice(lead.length).replace(/\s+$/, "");
    const tail = seg.del.slice(lead.length + core.length);
    span.append(lead);
    if (core) span.append(el("span", { class: "del" }, core, seg.ins.trim() ? el("b", { class: "fix" }, seg.ins.trim()) : null));
    else span.append(el("span", { class: "ins" }, el("b", { class: "caret-fix" }, seg.ins.trim())));
    span.append(tail);
  }
  return span;
}

// The mirror: red-pencil markup (in Mark-up mode) and a tint on paragraphs that are still
// Quill's AI-written text (always, since that's about who wrote it, not about editing).
function renderMarkup() {
  const text = $("#body").value;
  const ranges = writeMode() ? [] : suggestionRanges();
  const fill = (into, from, to) => {
    let at = from;
    for (const { start, end, s } of ranges) {
      if (start < at || end > to) continue;
      into.append(text.slice(at, start), markupFor(s, text.slice(start, end)));
      at = end;
    }
    into.append(text.slice(at, to));
  };
  const root = $("#backdrop");
  root.replaceChildren();
  const paras = state.aiText ? aiParagraphs(text, state.aiText, state.aiCache) : [];
  let at = 0;
  for (const p of paras.filter((x) => x.ai)) {
    fill(root, at, p.start);
    const span = el("span", { class: "ai-para" });
    fill(span, p.start, p.end);
    root.append(span);
    at = p.end;
  }
  fill(root, at, text.length);
  root.append("\n"); // keeps the last empty line the same height as in the textarea
  renderAiBanner(paras);
  placeNotes();
}

function renderAiBanner(paras) {
  const ai = paras.filter((p) => p.ai).length;
  const banner = $("#ai-banner");
  banner.hidden = !ai;
  banner.textContent = ai
    ? `${ai} of ${paras.length} paragraph${paras.length === 1 ? " is" : "s are"} still Quill's AI draft (tinted). The tint goes away as you rewrite ${ai === 1 ? "it" : "them"} in your own words.`
    : "";
}

// Screen position of a character offset in the draft, read from the mirror. Replacement words
// drawn above the line aren't part of the draft, so they're skipped while counting.
function offsetRect(offset) {
  const walker = document.createTreeWalker($("#backdrop"), NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement.closest(".fix, .caret-fix") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  let seen = 0;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (seen + n.length > offset) { // ">": an empty text node has no position of its own
      const range = document.createRange();
      range.setStart(n, offset - seen);
      range.setEnd(n, Math.min(n.length, offset - seen + 1));
      return range.getBoundingClientRect();
    }
    seen += n.length;
  }
  return null;
}

// Selects part of the draft and scrolls it into view (the textarea grows, so the page scrolls).
function selectText(start, end) {
  const body = $("#body");
  body.focus({ preventScroll: true });
  body.setSelectionRange(start, end);
  const rect = offsetRect(start);
  if (rect) window.scrollBy({ top: rect.top - window.innerHeight / 3, behavior: "smooth" });
}

const marginBeside = () => matchMedia("(min-width: 1001px)").matches;

// Margin notes sit level with the line they're about, pushed down only to avoid overlapping.
// On narrow screens the margin is below the page, so notes simply stack in reading order.
function placeNotes() {
  const list = $("#suggestion-list");
  const notes = state.suggestions.filter((s) => s.note.isConnected);
  const beside = marginBeside() && !$("#panel-edits").hidden && notes.length > 0 && !writeMode();
  list.classList.toggle("placed", beside);
  if (!beside) {
    notes.forEach((s) => { s.note.style.top = ""; });
    list.style.minHeight = "";
    return;
  }
  const origin = list.getBoundingClientRect().top;
  const wanted = notes.map((s) => {
    const mark = $(`#backdrop .mk[data-id="${s.id}"]`);
    return { s, top: mark ? mark.getBoundingClientRect().top - origin - 2 : Infinity };
  }).sort((a, b) => a.top - b.top);
  let floor = 0;
  for (const { s, top } of wanted) {
    const y = Math.max(Number.isFinite(top) ? top : floor, floor);
    s.note.style.top = `${y}px`;
    s.note.classList.toggle("stale", !Number.isFinite(top));
    floor = y + s.note.offsetHeight + 14;
  }
  list.style.minHeight = `${floor}px`;
}

function setActive(id, on) {
  $(`#backdrop .mk[data-id="${id}"]`)?.classList.toggle("active", on);
  state.suggestions.find((s) => s.id === id)?.note.classList.toggle("active", on);
}

// Clicking marked-up text in the draft points at its note.
$("#body").addEventListener("click", () => {
  const caret = $("#body").selectionStart;
  const hit = suggestionRanges().find((r) => caret >= r.start && caret <= r.end);
  if (!hit) return;
  setTab("edits");
  hit.s.note.scrollIntoView({ behavior: "smooth", block: "nearest" });
  setActive(hit.s.id, true);
  setTimeout(() => setActive(hit.s.id, false), 1600);
});

// ---------- review (streamed) ----------

function marginMessage(text) {
  return el("p", { class: "done-note" }, text);
}

function clearFeedback() {
  state.suggestions = [];
  state.current = null;
  $("#suggestion-list").replaceChildren(marginMessage("Press “Mark it up” and Quill reads each paragraph. Its notes appear here, beside the line they're about."));
  $("#voice-notes").replaceChildren();
  $("#overview-panel").replaceChildren();
  progress.hide();
  gutter.marks = [];
  renderGutter();
  updateCounts();
  renderMarkup();
}

// ---------- progress ----------

const clock = (s) => (s < 60 ? `0:${String(s).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
const roughly = (s) => (s < 50 ? `about ${Math.max(5, Math.round(s / 5) * 5)} s left` : `about ${Math.round(s / 60)} min left`);

// How long things took last time on this laptop, so estimates fit its speed.
function typical(kind, fallback) {
  return Number(storage(`quill-time-${kind}`)) || fallback;
}
function remember(kind, seconds) {
  const before = typical(kind, seconds);
  storage(`quill-time-${kind}`, String(Math.round((before * 2 + seconds) / 3))); // smoothed
}

// A progress readout: what's happening, a clock, and a bar. With a known number of steps the
// bar is split into one segment per step, and the current segment fills as the step's expected
// time passes. Without steps it creeps toward full over the expected time, slowing as it goes,
// so a long wait still visibly moves but never claims to be done early.
class Progress {
  constructor(root, onFraction = () => {}) {
    this.root = root;
    this.onFraction = onFraction;
    this.timer = null;
  }

  start(label, { kind, expected }) {
    Object.assign(this, { label, kind, expected: typical(kind, expected), total: 0, done: 0, queued: false,
      t0: Date.now(), stepStart: Date.now(), stepTimes: [] });
    this.root.hidden = false;
    this.root.classList.remove("failed", "finished");
    clearInterval(this.timer);
    this.timer = setInterval(() => this.tick(), 500);
    this.build();
  }

  queue(position) {
    this.label = queueText(position);
    this.queued = true;
    this.build();
  }

  steps(total, label) {
    Object.assign(this, { total, done: 0, queued: false, label, t0: Date.now(), stepStart: Date.now() });
    this.build();
  }

  step(done, label) {
    const now = Date.now();
    this.stepTimes.push((now - this.stepStart) / 1000);
    Object.assign(this, { done, label, stepStart: now });
    this.build();
  }

  begin(label) { // the model has started (after any wait in line)
    Object.assign(this, { label, queued: false, t0: Date.now() });
    this.build();
  }

  secondsPerStep() {
    if (this.stepTimes.length) return this.stepTimes.reduce((a, b) => a + b, 0) / this.stepTimes.length;
    return this.expected;
  }

  fraction() {
    const elapsed = (Date.now() - this.t0) / 1000;
    if (this.queued) return 0;
    if (this.total) {
      const partial = Math.min(0.9, (Date.now() - this.stepStart) / 1000 / this.secondsPerStep());
      return Math.min(1, (this.done + partial) / this.total);
    }
    return 0.95 * (1 - Math.exp(-elapsed / this.expected));
  }

  timeText() {
    const elapsed = Math.round((Date.now() - this.t0) / 1000);
    if (this.queued) return `waiting ${clock(elapsed)}`;
    if (this.total && this.stepTimes.length) {
      const left = this.secondsPerStep() * (this.total - this.done) - (Date.now() - this.stepStart) / 1000;
      return roughly(Math.max(5, left));
    }
    if (!this.total && elapsed < this.expected) {
      const usual = this.expected < 50 ? `${Math.round(this.expected / 5) * 5} s` : `${Math.round(this.expected / 60)} min`;
      return `${clock(elapsed)} · usually about ${usual}`;
    }
    return clock(elapsed);
  }

  build() {
    const segmented = this.total > 1 && this.total <= 40;
    const track = el("div", { class: `p-track${segmented ? " segs" : ""}${this.queued ? " waiting" : ""}` });
    if (segmented) {
      for (let i = 0; i < this.total; i++) {
        track.append(el("span", { class: i < this.done ? "seg done" : i === this.done ? "seg active" : "seg" }, el("i")));
      }
    } else {
      track.append(el("i"));
    }
    this.root.replaceChildren(
      el("div", { class: "p-head" }, el("span", { class: "p-label" }, this.label), el("span", { class: "p-time", "aria-hidden": "true" })),
      track);
    this.tick();
  }

  tick() {
    const time = this.root.querySelector(".p-time");
    if (time) time.textContent = this.timeText();
    const f = this.fraction();
    if (this.total > 1 && this.total <= 40) {
      const active = this.root.querySelector(".seg.active i");
      if (active) active.style.width = `${Math.round(Math.min(0.9, (Date.now() - this.stepStart) / 1000 / this.secondsPerStep()) * 100)}%`;
    } else {
      const fill = this.root.querySelector(".p-track > i");
      if (fill) fill.style.width = `${Math.max(2, Math.round(f * 100))}%`;
    }
    this.onFraction(f);
  }

  stopClock() {
    clearInterval(this.timer);
    this.timer = null;
  }

  finish() {
    if (this.total) this.stepTimes.push((Date.now() - this.stepStart) / 1000);
    if (!this.root.hidden && this.kind && !this.queued) {
      const seconds = (Date.now() - this.t0) / 1000;
      remember(this.kind, this.total ? this.secondsPerStep() : seconds);
    }
    this.stopClock();
    this.root.classList.add("finished");
    this.root.querySelectorAll(".seg").forEach((s) => s.classList.add("done"));
    const fill = this.root.querySelector(".p-track > i");
    if (fill) fill.style.width = "100%";
    this.onFraction(1);
    setTimeout(() => { if (!this.timer) { this.root.hidden = true; this.onFraction(null); } }, 900);
  }

  fail(message) {
    this.stopClock();
    this.root.hidden = false;
    this.root.classList.add("failed");
    this.root.replaceChildren(el("div", { class: "p-head" }, el("span", { class: "p-label" }, message)));
    this.onFraction(null);
  }

  hide() {
    this.stopClock();
    this.root.hidden = true;
    this.onFraction(null);
  }
}

// The margin's progress also drives a thin line along the phone's bottom bar, since on a phone
// the margin is below the essay and out of sight.
const progress = new Progress($("#progress"), (f) => {
  const app = $("#app-view");
  app.classList.toggle("busy", f != null);
  if (f != null) app.style.setProperty("--p", f);
});

// Marks in the left gutter beside each paragraph: a pencil on the one being read, a tick on
// those done. They sit level with the paragraph, measured from the markup mirror.
const gutter = { marks: [] }; // index -> "reading" | "done"

function renderGutter() {
  const box = $("#gutter");
  const text = $("#body").value;
  const spans = paragraphSpans(text);
  const origin = $(".text").getBoundingClientRect().top;
  box.replaceChildren(...gutter.marks.map((status, i) => {
    if (!status || !spans[i]) return null;
    const rect = offsetRect(spans[i].start);
    if (!rect) return null;
    const mark = el("span", { class: `g-mark ${status}` }, icon(status === "done" ? "i-check" : "i-pen"));
    mark.style.top = `${rect.top - origin}px`;
    return mark;
  }).filter(Boolean));
}

function markParagraph(index, status) {
  gutter.marks[index] = status;
  renderGutter();
}

function clearGutter(delay = 0) {
  setTimeout(() => {
    $("#gutter").classList.add("fading");
    setTimeout(() => {
      gutter.marks = [];
      $("#gutter").classList.remove("fading");
      renderGutter();
    }, 400);
  }, delay);
}

function queueText(position) {
  return position === 1
    ? "You're next. Quill is finishing someone else's essay."
    : `You're ${ordinal(position)} in line. Others are using Quill right now.`;
}

const grammarFixes = () => state.suggestions.filter((s) => s.category === "grammar" && s.revised != null);

function updateCounts() {
  const n = state.suggestions.length;
  $("#edit-count").textContent = n || "";
  moveTabIndicator();
  const g = grammarFixes().length;
  $("#bulk").hidden = n === 0;
  $("#accept-grammar").hidden = g < 2;
  $("#accept-grammar").textContent = `Accept all ${g} grammar fixes`;
  const jump = $("#jump-suggestions");
  jump.hidden = n === 0;
  jump.querySelector("span").textContent = `${n}`;
  jump.setAttribute("aria-label", `${n} note${n === 1 ? "" : "s"}`);
}

function addSuggestions(items) {
  const list = $("#suggestion-list");
  list.querySelector(".done-note")?.remove();
  for (const item of items) {
    const s = { ...item, id: nextId++ };
    s.note = noteFor(s);
    state.suggestions.push(s);
    list.append(s.note);
  }
  updateCounts();
  renderMarkup();
}

function removeSuggestion(s) {
  const i = state.suggestions.indexOf(s);
  state.suggestions = state.suggestions.filter((x) => x !== s);
  s.note.classList.add("leaving");
  setTimeout(() => s.note.remove(), matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 180);
  // Keyboard users land on the next note instead of losing their place.
  if (state.current === s) setCurrent(state.suggestions[Math.min(i, state.suggestions.length - 1)] || null);
  if (!state.suggestions.length && !state.run) {
    $("#suggestion-list").replaceChildren(marginMessage("That's everything. Mark it up again after you revise."));
  }
  updateCounts();
  renderMarkup();
}

function stopRun() {
  state.run?.abort();
  state.run = null;
}

const RUN_BUTTONS = ["#review", "#review-phone", "#overview"];

function setRunning(active) {
  for (const sel of RUN_BUTTONS) {
    const b = $(sel);
    const isActive = active && (sel === active || (active !== "#overview" && sel !== "#overview"));
    b.disabled = !state.draftId || (!!active && !isActive);
    b.classList.toggle("running", isActive);
    const svg = b.querySelector("svg");
    if (svg && !b.dataset.icon) b.dataset.icon = svg.querySelector("use").getAttribute("href").slice(1);
    if (!b.dataset.label) b.dataset.label = b.querySelector("span").textContent;
    if (svg) svg.replaceWith(icon(isActive ? "i-stop" : b.dataset.icon));
    b.querySelector("span").textContent = isActive ? "Stop" : b.dataset.label;
  }
}

async function runStream(trigger, path, onEvent, { kind, expected }) {
  if (state.run) { stopRun(); return; } // second click = Stop
  const body = $("#body").value.trim();
  if (!body) return;
  await saveVersion("Before review");
  const run = (state.run = new AbortController());
  setRunning(trigger);
  progress.start("Starting…", { kind, expected });
  let failed = false;
  try {
    await stream(path, { body, ...goals() }, (event) => {
      if (event.type === "queue") progress.queue(event.position);
      else if (event.type === "error") { failed = true; progress.fail(event.message); }
      else onEvent(event);
    }, run.signal);
    if (!failed) progress.finish();
  } catch (err) {
    progress.fail(err.name === "AbortError" ? "Stopped." : err.message);
  } finally {
    if (state.run === run) state.run = null;
    setRunning(null);
    clearGutter(failed ? 0 : 2000);
  }
}

function startReview(trigger) {
  if (writeMode()) setMode("markup"); // asking for notes means wanting to see them
  if (!state.run) {
    setTab("edits");
    state.suggestions.forEach((s) => s.note.remove());
    state.suggestions = [];
    state.current = null;
    $("#suggestion-list").replaceChildren();
    $("#voice-notes").replaceChildren();
    updateCounts();
    renderMarkup();
  }
  let modelCount = 0;
  runStream(trigger, "/api/review", (event) => {
    if (event.type === "instant") {
      $("#voice-notes").replaceChildren(...event.voice_notes.map((n) => el("p", { class: "drift" }, n)));
      addSuggestions(event.suggestions);
    } else if (event.type === "start") {
      progress.steps(event.total, `Paragraph 1 of ${event.total}`);
      gutter.marks = [];
      markParagraph(0, "reading");
    } else if (event.type === "paragraph") {
      modelCount += event.suggestions.length;
      addSuggestions(event.suggestions.map((s) => ({ ...s, paragraph: event.index })));
      const done = event.index + 1;
      gutter.marks[event.index] = "done";
      if (done < event.total) {
        progress.step(done, `Paragraph ${done + 1} of ${event.total}`);
        markParagraph(done, "reading");
      } else {
        renderGutter();
      }
    } else if (event.type === "done" && state.suggestions.length === 0) {
      $("#suggestion-list").replaceChildren(marginMessage("Nothing to mark. This reads well as it is."));
    } else if (event.type === "done" && modelCount === 0) {
      $("#suggestion-list").prepend(marginMessage("No corrections beyond the phrases flagged here."));
      placeNotes();
    }
  }, { kind: "paragraph", expected: 6 });
}

$("#review").addEventListener("click", () => startReview("#review"));
$("#review-phone").addEventListener("click", () => startReview("#review-phone"));

$("#overview").addEventListener("click", () => {
  if (!state.run) $("#overview-panel").replaceChildren();
  let notice = null;
  runStream("#overview", "/api/overview", (event) => {
    if (event.type === "start") progress.begin("Reading the whole essay");
    else if (event.type === "notice") notice = event.message;
    else if (event.type === "overview") {
      renderOverview(event.overview);
      if (notice) $("#overview-panel").prepend(el("p", { class: "notice" }, notice));
    }
  }, { kind: "letter", expected: 45 });
});

// The big-picture feedback, laid out as a short letter in the margin.
function renderOverview(o) {
  if (!o) {
    $("#overview-panel").replaceChildren(el("p", { class: "error" }, "Couldn't read the feedback. Try again."));
    return;
  }
  const section = (title, rating, text) => el("div", { class: "letter-block" },
    el("h4", {}, title, rating ? el("span", { class: `r ${rating.replace(/\s+/g, "-")}` }, rating) : null),
    el("p", {}, text));
  $("#overview-panel").replaceChildren(
    el("div", { class: "letter-block" }, el("h4", {}, "Work on this first"), el("p", { class: "first" }, o.top_priority)),
    ...o.comments.map((c) => section(c.aspect, c.rating, c.comment)),
    section("Keep this", null, o.strongest_part),
  );
}

// A margin note: the editor's reason in red pencil, then the choice.
function noteFor(s) {
  const note = el("div", {
    class: "note",
    onmouseenter: () => setActive(s.id, true),
    onmouseleave: () => setActive(s.id, false),
  });
  const act = (label, onclick, cls = "", title = null) => el("button", { class: cls, onclick, ...(title ? { title } : {}) }, label);
  note.append(el("span", {}, s.reason));
  const never = act("Never flag", () => neverFlag(s), "", `Quill won't flag “${ignorePhrase(s)}” again`);
  if (s.revised == null) {
    note.append(el("span", { class: "acts" }, act("Show me", () => highlight(s)), act("Got it", () => removeSuggestion(s)), never));
  } else {
    note.append(el("span", { class: "acts" },
      act("Accept", () => accept(s), "yes"),
      act("Skip", () => decide(s, false)),
      act("Show me", () => highlight(s)),
      never));
  }
  return note;
}

function sendFeedback(s, accepted) {
  const { note: _note, id: _id, ...payload } = s;
  api("/api/feedback", { method: "POST", body: { ...payload, draft_id: state.draftId, revised: s.revised ?? "", accepted } }).catch(() => {});
}

function decide(s, accepted) {
  sendFeedback(s, accepted);
  removeSuggestion(s);
}

function accept(s) {
  if (applyEdit(s)) decide(s, true);
}

// What "Never flag" remembers: a small word change is about those words ("gonna"), wherever they
// appear; anything bigger is about that exact sentence.
function ignorePhrase(s) {
  if (s.revised == null) return s.original;
  const changes = diffWords(s.original, s.revised).filter((seg) => seg.type === "change");
  const words = changes.length === 1 ? changes[0].del.trim() : "";
  return words && words.split(/\s+/).length <= 3 ? words : s.original;
}

async function neverFlag(s) {
  const phrase = ignorePhrase(s);
  try {
    state.ignored = await api("/api/ignored", { method: "POST", body: { phrase } });
  } catch (err) {
    alert(`Couldn't save that: ${err.message}`);
    return;
  }
  renderIgnored();
  if (s.revised != null) sendFeedback(s, false);
  const lower = phrase.toLowerCase();
  state.suggestions.filter((x) => x.original.toLowerCase().includes(lower)).forEach(removeSuggestion);
}

// ---------- notes from the keyboard ----------

function setCurrent(s) {
  state.current?.note.classList.remove("current");
  state.current = s;
  if (!s) return;
  s.note.classList.add("current");
  setTab("edits");
  s.note.scrollIntoView({ block: "nearest" });
  const at = locate(s, $("#body").value);
  if (at !== -1) selectText(at, at + s.original.length);
}

// Notes in reading order, so Alt+Down walks down the page.
function notesInOrder() {
  const text = $("#body").value;
  return [...state.suggestions].sort((a, b) => {
    const pa = locate(a, text), pb = locate(b, text);
    return (pa === -1 ? Infinity : pa) - (pb === -1 ? Infinity : pb);
  });
}

function moveCurrent(step) {
  const order = notesInOrder();
  const i = order.indexOf(state.current);
  const next = i === -1 ? (step > 0 ? 0 : order.length - 1) : Math.max(0, Math.min(order.length - 1, i + step));
  setCurrent(order[next]);
}

function actOnCurrent(yes) {
  const s = state.current;
  if (!s) { moveCurrent(1); return; }
  if (s.revised == null) removeSuggestion(s);
  else if (yes) accept(s);
  else decide(s, false);
}

// Accept every grammar fix at once, last first so earlier positions stay put. Each one is still
// its own step in Ctrl+Z.
$("#accept-grammar").addEventListener("click", () => {
  const text = $("#body").value;
  const fixes = grammarFixes().map((s) => ({ s, at: locate(s, text) })).filter((f) => f.at !== -1)
    .sort((a, b) => b.at - a.at);
  for (const { s, at } of fixes) {
    replaceRange(at, at + s.original.length, s.revised);
    decide(s, true);
  }
});

function highlight(s) {
  const body = $("#body");
  const at = locate(s, $("#body").value);
  if (at === -1) return false;
  body.focus({ preventScroll: true });
  body.setSelectionRange(at, at + s.original.length);
  // The textarea doesn't scroll itself, so bring the marked line into view.
  $(`#backdrop .mk[data-id="${s.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}

function applyEdit(s) {
  const at = locate(s, $("#body").value);
  if (at === -1) {
    alert("That text has changed since Quill read it, or now appears more than once, so this can't be applied automatically. Use Show me, or edit it by hand.");
    return false;
  }
  replaceRange(at, at + s.original.length, s.revised);
  return true;
}

// ---------- read-through report ----------

let reportTimer = null;
function scheduleReport() {
  clearTimeout(reportTimer);
  reportTimer = setTimeout(renderReport, 400);
}

function renderReport() {
  const text = $("#body").value;
  const r = readThrough(text);
  const box = $("#report");
  if (!r.words) {
    box.replaceChildren(el("p", { class: "none" }, "Write something and the report fills in."));
    return;
  }
  const preview = (start, end) => {
    const words = text.slice(start, end).split(/\s+/);
    return words.length > 9 ? `${words.slice(0, 9).join(" ")}…` : words.join(" ");
  };
  const find = (label, start, end, extra = null) =>
    el("button", { onclick: () => selectText(start, end) }, label, extra);
  const block = (title, ...children) => el("section", {}, el("h4", {}, title), ...children);
  const finds = (items, cls = "finds") => (items.length ? el("div", { class: cls }, ...items) : el("p", { class: "none" }, "None."));

  // Sentence rhythm: one bar per sentence, a gap between paragraphs.
  const paraStarts = new Set(paragraphSpans(text).map((p) => p.start));
  const rhythm = el("div", { class: "rhythm", role: "img", "aria-label": `Sentence lengths for ${r.sentences.length} sentences` },
    ...r.sentences.map((s, i) => {
      const bar = find("", s.start, s.end);
      bar.className = `${s.words > 30 ? "long" : ""}${i && paraStarts.has(s.start) ? " para-start" : ""}`;
      bar.style.height = `${Math.max(6, Math.min(100, (s.words / 40) * 100))}%`;
      bar.title = `Sentence ${i + 1}: ${s.words} words`;
      bar.setAttribute("aria-label", bar.title);
      return bar;
    }));

  const grade = Math.round(r.grade);
  box.replaceChildren(
    el("div", { class: "stats" },
      el("div", { class: "stat" }, el("b", {}, r.words.toLocaleString()), el("span", {}, "words")),
      el("div", { class: "stat" }, el("b", {}, String(r.sentences.length)), el("span", {}, "sentences")),
      el("div", { class: "stat" }, el("b", {}, r.avgWords.toFixed(1)), el("span", {}, "words per sentence")),
      el("div", { class: "stat", title: "Flesch-Kincaid grade level: an estimate from sentence and word length" },
        el("b", {}, grade < 1 ? "Easy" : `Grade ${grade}`), el("span", {}, "reading level"))),
    block("Sentence rhythm", rhythm,
      el("p", { class: "caption" }, r.long.length
        ? `Each bar is a sentence. ${r.long.length} run${r.long.length === 1 ? "s" : ""} past 30 words (in red); check ${r.long.length === 1 ? "it reads" : "they read"} clearly.`
        : "Each bar is a sentence. A row of bars the same height reads flat; varied lengths keep a reader moving.")),
    block("Words you lean on", finds(r.repeated.map((c) => find(c.word, c.start, c.end, el("small", {}, `×${c.count}`))))),
    block("Passive voice", finds(r.passive.slice(0, 8).map((p) => find(preview(p.start, p.end + 40).replace(/…$/, "") + "…", p.start, p.end)), "finds list"),
      r.passive.length ? el("p", { class: "caption" }, "Fine when who did it doesn't matter. Otherwise, try naming who acts.") : null),
    block("Adverbs", finds(r.adverbs.slice(0, 16).map((a) => find(a.text, a.start, a.end))),
      r.adverbs.length > 3 ? el("p", { class: "caption" }, "A stronger verb can often do the adverb's job.") : null),
  );
}

// ---------- drafting from a prompt ----------

let composeRun = null;
const composeProgress = new Progress($("#compose-progress"));

function voiceName() {
  const p = state.profile;
  if (!p) return "your voice";
  if (p.voice_mode === "preset") return state.voices?.presets.find((v) => v.id === p.preset_id)?.name || "a ready-made voice";
  if (p.voice_mode === "custom") return "your custom voice";
  return p.samples.length ? "the voice from your writing samples" : "a neutral voice, since you haven't picked one";
}

function openCompose() {
  closeDrawer();
  $("#compose-voice").textContent = voiceName();
  if (!composeRun) composeProgress.hide();
  $("#compose-dialog").showModal();
  $("#compose-form").instructions.focus();
}

function closeCompose() {
  composeRun?.abort();
  $("#compose-dialog").close();
}
$$("#compose-dialog [data-close]").forEach((b) => b.addEventListener("click", closeCompose));
$("#compose-dialog").addEventListener("cancel", () => composeRun?.abort());
$("#compose-change-voice").addEventListener("click", () => { closeCompose(); setView("voice"); });

$("#compose-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (composeRun) { composeRun.abort(); return; } // second click = Stop
  const form = e.target;
  const body = Object.fromEntries(["instructions", "goal", "audience", "tone", "length"].map((k) => [k, form[k].value]));
  const go = $("#compose-go span");
  const run = (composeRun = new AbortController());
  go.textContent = "Stop";
  // Longer drafts take longer; each length keeps its own estimate.
  const expected = { short: 40, medium: 75, long: 130 }[body.length] || 75;
  composeProgress.start("Starting…", { kind: `draft-${body.length}`, expected });
  let draftId = null, failed = false;
  try {
    await saveVersion("Switched essays");
    await stream("/api/compose", body, (event) => {
      if (event.type === "queue") composeProgress.queue(event.position);
      else if (event.type === "start") composeProgress.begin("Writing the draft");
      else if (event.type === "error") { failed = true; composeProgress.fail(event.message); }
      else if (event.type === "draft") draftId = event.id;
    }, run.signal);
    if (!failed && draftId) composeProgress.finish();
  } catch (err) {
    composeProgress.fail(err.name === "AbortError" ? "Stopped." : err.message);
  } finally {
    composeRun = null;
    go.textContent = "Write the draft";
  }
  if (draftId) {
    await new Promise((r) => setTimeout(r, 500)); // let the full bar show for a moment
    $("#compose-dialog").close();
    form.reset();
    await openDraft(draftId);
  }
});

// ---------- replay ----------

const replay = { versions: [], index: 0, timer: null };

// Paragraph-level alignment first, then a word diff inside paragraphs that changed, so long
// essays don't need one huge diff.
function diffParagraphs(before, after) {
  const a = paragraphSpans(before).map((p) => before.slice(p.start, p.end));
  const b = paragraphSpans(after).map((p) => after.slice(p.start, p.end));
  const lcs = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out = []; // {before?, after?}
  let i = 0, j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) { out.push({ before: a[i++], after: b[j++] }); continue; }
    // A removed paragraph followed by an added one is the same paragraph, edited.
    if (i < a.length && j < b.length && lcs[i + 1][j + 1] === lcs[i][j]) { out.push({ before: a[i++], after: b[j++] }); continue; }
    if (j < b.length && (i === a.length || lcs[i][j + 1] >= lcs[i + 1][j])) out.push({ after: b[j++] });
    else out.push({ before: a[i++] });
  }
  return out;
}

function renderReplay() {
  const { versions, index } = replay;
  const v = versions[index];
  const prev = index ? versions[index - 1].body : "";
  const who = v.source === "ai" ? "AI-written"
    : v.ai_paragraphs.some(Boolean) ? `${v.ai_paragraphs.filter(Boolean).length} of ${v.ai_paragraphs.length} paragraphs still AI-written`
      : "Written by you";
  $("#replay-label").textContent = `Version ${index + 1} of ${versions.length} · ${fmtDate(v.created)} · ${v.note || "Autosave"}${v.note === "Drafted by Quill AI" ? "" : ` · ${who}`}`;
  $("#replay-slider").value = index;
  $("#replay-prev").disabled = index === 0;
  $("#replay-next").disabled = index === versions.length - 1;
  let n = 0; // index among this version's paragraphs, to match ai_paragraphs
  const paras = diffParagraphs(prev, v.body).map(({ before, after }) => {
    if (after == null) return el("p", {}, el("del", {}, before));
    const p = el("p", { class: v.ai_paragraphs[n++] ? "ai-para" : "" });
    if (before == null) p.append(el("ins", {}, after));
    else if (before === after) p.append(after);
    else for (const seg of diffWords(before, after)) {
      if (seg.type === "keep") p.append(seg.del);
      else p.append(seg.del.trim() ? el("del", {}, seg.del) : "", seg.ins.trim() ? el("ins", {}, seg.ins) : "");
    }
    return p;
  });
  $("#replay-body").replaceChildren(...(paras.length ? paras : [el("p", { class: "none" }, "This version is empty.")]));
}

function stopReplay() {
  clearInterval(replay.timer);
  replay.timer = null;
  $("#replay-play span").textContent = "Play";
}

function stepReplay(to) {
  replay.index = Math.max(0, Math.min(replay.versions.length - 1, to));
  renderReplay();
}

$("#replay").addEventListener("click", async () => {
  await saveVersion("Before replay");
  replay.versions = await api(`/api/drafts/${state.draftId}/replay`);
  if (!replay.versions.length) return;
  $("#replay-slider").max = replay.versions.length - 1;
  $("#replay-title").textContent = `How “${$("#title").value.trim() || "Untitled essay"}” was written`;
  stepReplay(0);
  $("#replay-dialog").showModal();
});
$("#replay-prev").addEventListener("click", () => { stopReplay(); stepReplay(replay.index - 1); });
$("#replay-next").addEventListener("click", () => { stopReplay(); stepReplay(replay.index + 1); });
$("#replay-slider").addEventListener("input", (e) => { stopReplay(); stepReplay(Number(e.target.value)); });
$("#replay-play").addEventListener("click", () => {
  if (replay.timer) { stopReplay(); return; }
  if (replay.index === replay.versions.length - 1) stepReplay(0);
  $("#replay-play span").textContent = "Pause";
  replay.timer = setInterval(() => {
    if (replay.index >= replay.versions.length - 1) stopReplay();
    else stepReplay(replay.index + 1);
  }, 1400);
});
$("#replay-dialog").addEventListener("close", stopReplay);

// ---------- voice ----------

const CUSTOM_LABELS = {
  formality: ["Formality", { casual: "Casual", balanced: "In between", formal: "Formal" }],
  sentences: ["Sentence length", { short: "Short", medium: "Medium", long: "Long" }],
  contractions: ["Contractions", { yes: "Use them", no: "Avoid them" }],
  person: ["Point of view", { first: "I and me", third: "Keep myself out" }],
  humor: ["Humor", { none: "None", light: "A little", lots: "Plenty" }],
};

function addSample(text = "") {
  const t = el("textarea", { placeholder: "Paste something you wrote, like an old essay, a blog post or a long email", "aria-label": "Writing sample" });
  t.value = text;
  $("#samples").append(t);
  return t;
}
$("#add-sample").addEventListener("click", () => addSample().focus());

function renderProfile(p) {
  state.profile = p;
  $$('input[name="voice-mode"]').forEach((r) => { r.checked = r.value === p.voice_mode; });
  $$("[data-mode-panel]").forEach((section) => {
    // Samples stay visible under "Match each essay" too: they still power the voice-drift notes.
    section.hidden = !(section.dataset.modePanel === p.voice_mode || (section.dataset.modePanel === "samples" && p.voice_mode === "auto"));
  });
  $$("#preset-list .preset").forEach((b) => b.setAttribute("aria-checked", b.dataset.id === p.preset_id));
  $$("#custom-options input").forEach((r) => { r.checked = p.custom[r.name] === r.value; });
  let summary = p.active;
  if (p.voice_mode === "auto") summary = "Measured from each essay as Quill reads it.";
  else if (p.voice_mode === "samples" && !p.samples.length) summary = "No samples saved yet, so Quill measures each essay instead. Add some above.";
  $("#voice-summary").textContent = summary;
}

async function saveProfile(changes, statusEl = $("#mode-status")) {
  try {
    renderProfile(await api("/api/profile", { method: "PUT", body: changes }));
    statusEl.textContent = "Saved.";
    statusEl.classList.remove("bad");
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.classList.add("bad");
  }
}

async function loadProfile() {
  const [p, voices] = await Promise.all([api("/api/profile"), api("/api/voices")]);
  state.voices = voices;
  $("#preset-list").replaceChildren(...voices.presets.map((v) =>
    el("button", { class: "preset", role: "radio", "data-id": v.id, "aria-checked": "false",
      onclick: () => saveProfile({ voice_mode: "preset", preset_id: v.id }) },
      el("b", {}, v.name), el("span", {}, v.blurb), el("q", {}, v.sample))));
  $("#custom-options").replaceChildren(...Object.entries(voices.custom_options).map(([key, values]) => {
    const [label, names] = CUSTOM_LABELS[key] || [key, {}];
    return el("fieldset", {}, el("legend", {}, label),
      el("div", { class: "segmented" }, ...values.map((value) =>
        el("label", {}, el("input", { type: "radio", name: key, value,
          onchange: () => saveProfile({ voice_mode: "custom", custom: { ...state.profile.custom, [key]: value } }) }),
        el("span", {}, names[value] || value)))));
  }));
  $("#samples").replaceChildren();
  (p.samples.length ? p.samples : ["", "", ""]).forEach((t) => addSample(t));
  renderProfile(p);
}

$$('input[name="voice-mode"]').forEach((r) => r.addEventListener("change", () => {
  const changes = { voice_mode: r.value };
  // Picking "ready-made" before any preset starts from the first one.
  if (r.value === "preset" && !state.profile.preset_id) changes.preset_id = state.voices.presets[0].id;
  saveProfile(changes);
}));

$("#save-profile").addEventListener("click", () => {
  const samples = $$("#samples textarea").map((t) => t.value).filter((t) => t.trim());
  if (!samples.length) { $("#profile-status").textContent = "Add at least one sample."; return; }
  saveProfile({ samples }, $("#profile-status"));
});

$("#upload-sample").addEventListener("click", () => $("#sample-file").click());
$("#sample-file").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  for (const file of files) {
    try {
      const { text } = await api("/api/voice/sample-file", { method: "POST", body: await file.arrayBuffer() });
      const empty = $$("#samples textarea").find((t) => !t.value.trim());
      (empty || addSample()).value = text;
      $("#profile-status").textContent = `Added ${file.name}. Save to use it.`;
    } catch (err) {
      $("#profile-status").textContent = `${file.name}: ${err.message}`;
    }
  }
});

// ---------- never flag ----------

function renderIgnored() {
  $("#ignored-list").replaceChildren(...(state.ignored.length
    ? state.ignored.map((phrase) => el("li", {}, phrase,
        el("button", { class: "icon-btn", "aria-label": `Flag “${phrase}” again`, title: "Flag it again", onclick: () => unignore(phrase) }, icon("i-x"))))
    : [el("li", { class: "none" }, "Nothing yet.")]));
}

async function loadIgnored() {
  state.ignored = await api("/api/ignored");
  renderIgnored();
}

async function unignore(phrase) {
  state.ignored = await api(`/api/ignored?phrase=${encodeURIComponent(phrase)}`, { method: "DELETE" });
  renderIgnored();
}

$("#ignore-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = e.target.phrase;
  state.ignored = await api("/api/ignored", { method: "POST", body: { phrase: input.value } });
  input.value = "";
  renderIgnored();
});

// ---------- account ----------

$("#password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const status = $("#password-status");
  status.classList.remove("bad");
  if (form.new.value !== form.confirm.value) {
    status.textContent = "The new passwords don't match.";
    status.classList.add("bad");
    return;
  }
  try {
    const r = await api("/api/password", { method: "POST", body: { current: form.current.value, new: form.new.value } });
    form.reset();
    $("#account-username").value = $("#account-name").textContent; // reset() clears it
    status.textContent = r.signed_out
      ? `Password changed. Signed out of ${r.signed_out} other session${r.signed_out === 1 ? "" : "s"}.`
      : "Password changed.";
  } catch (err) {
    status.textContent = err.message;
    status.classList.add("bad");
  }
});

// ---------- boot ----------

setMode(storage("quill-mode") === "write" ? "write" : "markup");
state.token = storage("quill-token");
state.token ? showApp() : signOut();
