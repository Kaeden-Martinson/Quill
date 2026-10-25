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

// ---------- views, sidebar, tabs ----------

const VIEWS = ["write", "voice", "lab"];
const currentView = () => VIEWS.find((v) => !$(`#${v}-view`).hidden);

function setView(view) {
  const changed = $(`#${view}-view`).hidden;
  for (const v of VIEWS) $(`#${v}-view`).hidden = v !== view;
  $("#app-view").classList.toggle("away", view !== "write"); // no essay tools on other pages
  closeWordPop();
  if (view === "lab") openLab();
  updateCrumb();
  syncSidebar();
  closeSide();
  if (changed) window.scrollTo({ top: 0 });
  if (view === "write") requestAnimationFrame(() => { placeNotes(); moveTabIndicator(); });
}

$$("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
$("#home").addEventListener("click", () => setView("write"));

// The bar gets a hairline once the page scrolls under it.
addEventListener("scroll", () => $("#bar").classList.toggle("scrolled", scrollY > 4), { passive: true });

// ---------- sidebar ----------
// Wide screens: always there, and it can shrink to a rail of icons (remembered).
// Narrow screens: it slides in over the page from the menu button.

const overlayMode = () => matchMedia("(max-width: 900px)").matches;

// The margin sits beside the essay only when there's room for both, which depends on the
// sidebar as well as the window, so it follows the content area's actual width.
new ResizeObserver(([entry]) => {
  const narrow = entry.contentRect.width < 860;
  if (narrow === $("#app-view").classList.contains("narrow")) return;
  $("#app-view").classList.toggle("narrow", narrow);
  requestAnimationFrame(() => { placeNotes(); moveTabIndicator(); });
}).observe($(".content"));

function setCollapsed(collapsed) {
  $("#app-view").classList.toggle("side-collapsed", collapsed);
  $("#collapse").setAttribute("aria-expanded", !collapsed);
  $("#collapse").setAttribute("aria-label", collapsed ? "Expand the sidebar" : "Collapse the sidebar");
  storage("quill-side", collapsed ? "collapsed" : "open");
  // In the rail, icons are named by their tooltips.
  $$("#sidebar [data-tip]").forEach((b) => (collapsed ? b.setAttribute("title", b.dataset.tip) : b.removeAttribute("title")));
  requestAnimationFrame(() => { placeNotes(); moveTabIndicator(); renderGutter(); });
}
$("#collapse").addEventListener("click", () => setCollapsed(!$("#app-view").classList.contains("side-collapsed")));

let sideOpener = null;

function toggleSide(open = !$("#app-view").classList.contains("side-open")) {
  if (!overlayMode()) return;
  const wasOpen = $("#app-view").classList.contains("side-open");
  $("#app-view").classList.toggle("side-open", open);
  $("#scrim").hidden = !open;
  // While the sidebar covers the page, everything behind it is inert: keyboard and screen-reader
  // focus stay inside it instead of wandering into content you can't see.
  $(".content").inert = open;
  $("#open-side").setAttribute("aria-expanded", open);
  if (open && !wasOpen) {
    sideOpener = document.activeElement;
    $("#close-side").focus();
  } else if (!open && wasOpen) {
    if (sideOpener?.isConnected && !sideOpener.closest("[inert]")) sideOpener.focus();
    sideOpener = null;
  }
}
const closeSide = () => toggleSide(false);
$("#open-side").addEventListener("click", () => toggleSide(true));
$("#close-side").addEventListener("click", closeSide);
$("#scrim").addEventListener("click", closeSide);
// Growing the window past the breakpoint leaves overlay mode cleanly.
matchMedia("(max-width: 900px)").addEventListener("change", (e) => {
  if (!e.matches) {
    $("#app-view").classList.remove("side-open");
    $("#scrim").hidden = true;
    $(".content").inert = false;
  }
});

// Find an essay: expands the sidebar (or slides it in) and puts the cursor in the search box.
function findEssay() {
  if (overlayMode()) toggleSide(true);
  else if ($("#app-view").classList.contains("side-collapsed")) setCollapsed(false);
  $("#draft-filter").focus();
  $("#draft-filter").select();
}
$(".search").addEventListener("click", (e) => {
  if ($("#app-view").classList.contains("side-collapsed")) { e.preventDefault(); findEssay(); }
});

// "This essay": jump straight to a margin tab.
$$(".side-item[data-goto]").forEach((b) => b.addEventListener("click", () => {
  setView("write");
  if (writeMode()) setMode("markup"); // the margin is hidden in Write mode
  setTab(b.dataset.goto);
  $("#inspector").scrollIntoView({ behavior: "smooth", block: "nearest" });
}));

// Which sidebar items are "here": the open essay, the margin tab, or the voice page.
function syncSidebar() {
  const view = currentView();
  const tab = $(".tab.active")?.dataset.tab;
  $$(".side-item").forEach((b) => {
    const here = b.dataset.view ? b.dataset.view === view : view === "write" && !!state.draftId && b.dataset.goto === tab;
    here ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current");
  });
  $("#side-essay").hidden = !state.draftId;
  $("#side-notes").textContent = $("#edit-count").textContent;
  $("#side-versions").textContent = $("#version-count").textContent;
}

// ---------- an essay's actions menu ----------

const itemMenu = { draft: null, opener: null };

function openItemMenu(draft, button) {
  const menu = $("#item-menu");
  if (itemMenu.draft === draft && menu.classList.contains("open")) { closeItemMenu(); return; }
  itemMenu.draft = draft;
  itemMenu.opener = button;
  const r = button.getBoundingClientRect();
  menu.classList.add("open");
  const below = r.bottom + 6 + menu.offsetHeight < innerHeight;
  menu.style.left = `${Math.min(r.left, innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${below ? r.bottom + 6 : r.top - menu.offsetHeight - 6}px`;
  button.setAttribute("aria-expanded", "true");
  menu.querySelector("[role=menuitem]").focus();
}

function closeItemMenu(refocus = false) {
  const menu = $("#item-menu");
  if (!menu.classList.contains("open")) return;
  menu.classList.remove("open");
  itemMenu.opener?.setAttribute("aria-expanded", "false");
  if (refocus) itemMenu.opener?.focus();
}

document.addEventListener("click", (e) => {
  if (!e.target.closest("#item-menu, .d-more")) closeItemMenu();
});
addEventListener("resize", () => closeItemMenu());
$(".side-scroll").addEventListener("scroll", () => closeItemMenu(), { passive: true });

$("#item-menu").addEventListener("keydown", (e) => {
  const items = $$("#item-menu [role=menuitem]");
  const i = items.indexOf(document.activeElement);
  const next = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: items.length - 1 }[e.key];
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeItemMenu(true); return; }
  if (e.key === "Tab") { closeItemMenu(); return; }
  if (next === undefined) return;
  e.preventDefault();
  items[(next + items.length) % items.length].focus();
});

$("#item-menu").addEventListener("click", async (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act;
  const d = itemMenu.draft;
  if (!act || !d) return;
  closeItemMenu();
  if (act === "open") openDraft(d.id);
  else if (act === "rename") startRename(d);
  else if (act === "delete") confirmDelete(d);
  else if (act === "word") {
    if (d.id === state.draftId) await saveVersion("Before Word export");
    const res = await request(`/api/drafts/${d.id}/export.docx`);
    download(await res.blob(), `${d.title || "essay"}.docx`);
  }
});

// Rename in place: the title becomes a text field; Enter saves, Escape cancels.
function startRename(d) {
  const row = $(`#draft-list li[data-id="${d.id}"]`);
  if (!row) return;
  const input = el("input", { class: "rename", value: d.title, maxlength: "200", "aria-label": "Essay title" });
  row.replaceChildren(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const title = input.value.trim();
    if (save && title && title !== d.title) {
      try {
        await api(`/api/drafts/${d.id}`, { method: "PATCH", body: { title } });
        if (d.id === state.draftId) { $("#title").value = title; updateCrumb(); }
      } catch (err) { alert(`Couldn't rename: ${err.message}`); }
    }
    await loadDrafts();
    $(`#draft-list li[data-id="${d.id}"] .d-open`)?.focus();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

function setTab(name) {
  $$(".tab").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1; // one tab stop for the whole tab list; arrows move within it
  });
  $$(".panel").forEach((p) => { p.hidden = p.dataset.panel !== name; });
  moveTabIndicator();
  syncSidebar();
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
  for (const id of ["#review", "#review-phone", "#overview", "#polish", "#save", "#replay", "#export", "#export-docx", "#delete-draft"]) $(id).disabled = !enabled;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeItemMenu(); closeSide(); }
  // Ctrl+K (Cmd+K on a Mac) finds an essay from anywhere.
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && !$("#app-view").hidden) {
    e.preventDefault();
    findEssay();
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
      ? shown.map((d) => {
          const here = d.id === state.draftId;
          return el("li", { "data-id": d.id, class: here ? "active" : "" },
            el("button", { class: "d-open", "aria-current": here ? "page" : "false", title: d.title,
              onclick: () => openDraft(d.id), oncontextmenu: (e) => { e.preventDefault(); openItemMenu(d, e.currentTarget.nextSibling); } },
              el("svg", {}),
              el("span", { class: "d-title" }, d.title),
              el("span", { class: "d-meta" }, `${d.versions} version${d.versions === 1 ? "" : "s"} · ${fmtDate(d.updated)}`)),
            el("button", { class: "d-more", "aria-label": `Actions for ${d.title}`, "aria-haspopup": "menu", "aria-expanded": "false",
              onclick: (e) => { e.stopPropagation(); openItemMenu(d, e.currentTarget); } }, icon("i-dots")));
        })
      : [el("li", { class: "empty-list" }, drafts.length ? "No essay by that name." : "No essays yet. Start one above.")])
  );
  // el() can't make SVG; swap the placeholder for the document icon (shown in the collapsed rail).
  $$("#draft-list .d-open > svg").forEach((svg) => svg.replaceWith(icon("i-doc")));
}

$("#draft-filter").addEventListener("input", renderDraftList);
$("#sidebar").addEventListener("keydown", (e) => {
  if (!["ArrowDown", "ArrowUp", "Enter"].includes(e.key) || e.target.closest("#item-menu, .rename")) return;
  if (!e.target.closest(".search, #draft-list")) return;
  const items = $$("#draft-list .d-open");
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
  syncSidebar();
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

// Deleting works on any essay: the open one (History tab) or one picked from the sidebar.
let deleteTarget = null;

function confirmDelete(d) {
  deleteTarget = d;
  $("#delete-title").textContent = d.title || "Untitled essay";
  $("#delete-versions").textContent = d.versions || "0";
  $("#delete-dialog").returnValue = "";
  $("#delete-dialog").showModal();
}

$("#delete-draft").addEventListener("click", () => confirmDelete({
  id: state.draftId, title: $("#title").value.trim(), versions: $("#version-count").textContent,
}));

$("#delete-dialog").addEventListener("close", async () => {
  const target = deleteTarget;
  deleteTarget = null;
  if ($("#delete-dialog").returnValue !== "delete" || !target) return;
  const id = target.id;
  if (id === state.draftId) stopRun();
  try {
    await api(`/api/drafts/${id}`, { method: "DELETE" });
  } catch (err) {
    alert(`Couldn't delete: ${err.message}`);
    return;
  }
  if (id !== state.draftId) { loadDrafts(); return; }
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
  syncSidebar();
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

const marginBeside = () => !$("#app-view").classList.contains("narrow");

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

// Typo and grammar corrections only; rewrites always need their own yes (isCorrection in text.js).
const grammarFixes = () => state.suggestions.filter(isCorrection);

function updateCounts() {
  const n = state.suggestions.length;
  $("#edit-count").textContent = n || "";
  moveTabIndicator();
  syncSidebar();
  const g = grammarFixes().length;
  $("#bulk").hidden = n === 0;
  $("#accept-grammar").hidden = g < 2;
  $("#accept-grammar").textContent = `Accept all ${g} typo and grammar fixes`;
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

// How much Quill suggests: typos only, typos and grammar, or everything (rewrites and style notes too).
// Remembered per browser; the server labels and filters each suggestion (backend/localize.py).
function editMode() {
  return $("#edit-mode").value;
}
$("#edit-mode").value = ["typos", "grammar", "all"].includes(storage("quill-edit-mode")) ? storage("quill-edit-mode") : "all";
$("#edit-mode").addEventListener("change", () => storage("quill-edit-mode", editMode()));

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
    await stream(path, { body, ...goals(), mode: editMode() }, (event) => {
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
  if (s.kind === "rewrite" && s.revised != null) note.append(el("span", { class: "kind" }, "Rewrite"));
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


// ---------- polish: paragraphs rewritten for grammar and flow, each one the writer's choice ----------

let polishRun = null;
let polishTaken = 0;
const polishProgress = new Progress($("#polish-progress"));

function polishDiff(original, revised) {
  const out = el("p", { class: "polish-diff" });
  for (const seg of diffWords(original, revised)) {
    if (seg.type === "keep") out.append(seg.del);
    else {
      if (seg.del.trim()) out.append(el("del", {}, seg.del));
      if (seg.ins.trim()) out.append(el("ins", {}, seg.ins));
    }
  }
  return out;
}

// Puts a polished paragraph into the essay (one Ctrl+Z step) and records it as Quill's writing.
async function takePolish(e, card) {
  const text = $("#body").value;
  const span = paragraphSpans(text)[e.index];
  let start = span && text.slice(span.start, span.end) === e.original ? span.start : text.indexOf(e.original);
  if (start === -1) {
    card.querySelector(".acts").replaceChildren(el("span", { class: "aside" }, "This paragraph changed since Quill read it, so it was left alone."));
    return;
  }
  replaceRange(start, start + e.original.length, e.revised);
  polishTaken += 1;
  card.classList.add("taken");
  card.querySelector(".acts").replaceChildren(el("span", { class: "aside" }, "Used. Ctrl+Z puts yours back."));
  try {
    const r = await api(`/api/drafts/${state.draftId}/ai-text`, { method: "POST", body: { paragraphs: [e.revised] } });
    state.aiText = r.ai_text;
    state.aiCache = new Map();
    renderMarkup();
  } catch { /* the paragraph is in; the margin catches up next time the essay opens */ }
}

function polishCard(e) {
  const card = el("div", { class: "polish-card" });
  if (e.revised === e.original) {
    card.append(el("p", { class: "aside" }, `Paragraph ${e.index + 1}: ${e.checks.warnings[0] || "already reads well; Quill left it as it is."}`));
    return card;
  }
  card.append(el("h4", {}, `Paragraph ${e.index + 1}`), polishDiff(e.original, e.revised));
  if (e.checks.warnings.length) card.append(el("ul", { class: "polish-warn" }, ...e.checks.warnings.map((w) => el("li", {}, w))));
  card.append(el("div", { class: "acts" },
    el("button", { class: "btn ink", onclick: () => takePolish(e, card) }, "Use this"),
    el("button", { class: "btn quiet", onclick: () => { card.classList.add("kept"); card.querySelector(".acts").replaceChildren(el("span", { class: "aside" }, "Kept yours.")); } }, "Keep mine")));
  return card;
}

$("#polish").addEventListener("click", () => {
  closeSide();
  if (!polishRun) { $("#polish-list").replaceChildren(); polishProgress.hide(); }
  $("#polish-dialog").showModal();
});

$("#polish-go").addEventListener("click", async () => {
  if (polishRun) { polishRun.abort(); return; } // second click = Stop
  const body = $("#body").value.trim();
  if (!body) return;
  await saveVersion("Before polish");
  polishTaken = 0;
  $("#polish-list").replaceChildren();
  const run = (polishRun = new AbortController());
  const go = $("#polish-go span");
  go.textContent = "Stop";
  polishProgress.start("Starting…", { kind: "polish", expected: 20 * paragraphSpans(body).length });
  try {
    await stream("/api/polish", { body, ...goals() }, (event) => {
      if (event.type === "queue") polishProgress.queue(event.position);
      else if (event.type === "start") polishProgress.steps(event.total, `Paragraph 1 of ${event.total}`);
      else if (event.type === "paragraph") {
        $("#polish-list").append(polishCard(event));
        polishProgress.step(event.step + 1, event.step + 1 < event.total ? `Paragraph ${event.step + 2} of ${event.total}` : "Done");
      } else if (event.type === "error") polishProgress.fail(event.message);
    }, run.signal);
    polishProgress.finish();
  } catch (err) {
    polishProgress.fail(err.name === "AbortError" ? "Stopped." : err.message);
  } finally {
    polishRun = null;
    go.textContent = "Polish the essay";
  }
});

function closePolish() {
  polishRun?.abort();
  $("#polish-dialog").close();
  if (polishTaken) saveVersion("Polished by Quill AI");
  polishTaken = 0;
}
$$("#polish-dialog [data-close]").forEach((b) => b.addEventListener("click", closePolish));
$("#polish-dialog").addEventListener("cancel", () => { polishRun?.abort(); if (polishTaken) saveVersion("Polished by Quill AI"); polishTaken = 0; });

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
  closeSide();
  $("#compose-voice").textContent = voiceName();
  if (!composeRun) composeProgress.hide();
  const form = $("#compose-form");
  delete form.dataset.askedDetails;
  $("#compose-details-why").classList.remove("asking");
  if (!["detail1", "detail2", "detail3"].some((k) => form[k].value.trim())) $("#compose-details").open = false;
  if (!["example1", "example2", "example3"].some((k) => form[k].value.trim())) $("#compose-examples").open = false;
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
  body.details = ["detail1", "detail2", "detail3"].map((k) => form[k].value.trim()).filter(Boolean);
  body.examples = ["example1", "example2", "example3"].map((k) => form[k].value.trim()).filter(Boolean);
  // Ask first: for a piece about the writer's own life, offer the details fields once before drafting.
  // A second click drafts anyway; nothing here is required.
  if (looksPersonal(body.goal, body.instructions) && !body.details.length && !form.dataset.askedDetails) {
    form.dataset.askedDetails = "1";
    $("#compose-details").open = true;
    $("#compose-details-why").classList.add("asking");
    form.detail1.focus();
    return;
  }
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
    $("#compose-details").open = false;
    $("#compose-examples").open = false;
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

// ---------- settings lab ----------

const SLIDERS = [
  { name: "temperature", label: "Temperature", min: 0, max: 2, step: 0.05,
    hint: (v) => (v === 0 ? "Always the likeliest word." : v < 0.5 ? "Mostly the likeliest words." : v <= 1 ? "Natural variety." : "Loose; can wander.") },
  { name: "top_p", label: "top_p", min: 0, max: 1, step: 0.01,
    hint: (v) => (v >= 1 ? "Off: every word stays in the running." : `Keeps the likeliest words until they add up to ${Math.round(v * 100)}%.`) },
  { name: "min_p", label: "min_p", min: 0, max: 0.5, step: 0.01,
    hint: (v) => (v <= 0 ? "Off." : `Drops words less than ${Math.round(v * 100)}% as likely as the top one.`) },
  { name: "top_k", label: "top_k", min: 0, max: 100, step: 1,
    hint: (v) => (v <= 0 ? "Off." : `Only the ${v} likeliest words can be picked.`) },
];
const OFF = { temperature: 0, top_p: 1, min_p: 0, top_k: 0 };
const PRESETS = [
  { id: "edit", label: "Quill's edits" },
  { id: "draft", label: "Quill's drafting" },
  { id: "strict", label: "Likeliest only", values: { ...OFF } },
  { id: "loose", label: "Loose", values: { ...OFF, temperature: 1.3 } },
];

const labState = { defaults: null, cols: {}, ready: false };

function labMode() {
  return $('input[name="lab-mode"]:checked').value;
}

function presetValues(id) {
  const preset = PRESETS.find((p) => p.id === id);
  if (preset.values) return { ...preset.values };
  // Quill's own settings for that job; anything it leaves unset is shown as off.
  return { ...OFF, ...labState.defaults?.[id] };
}

function buildColumn(col, start) {
  const box = $(`.lab-col[data-col="${col}"]`);
  const c = (labState.cols[col] = { values: presetValues(start), result: null, ranWith: null });
  const sliders = SLIDERS.map((s) => {
    const input = el("input", { type: "range", min: s.min, max: s.max, step: s.step, "aria-label": `${s.label} for ${col.toUpperCase()}` });
    const value = el("output", {});
    const hint = el("p", { class: "lab-hint" });
    const show = () => {
      const v = Number(input.value);
      value.textContent = s.name === "top_k" ? String(v) : v.toFixed(2);
      hint.textContent = s.hint(v);
      // The cutoffs do nothing when temperature is 0, so say so instead of letting them look active.
      const idle = s.name !== "temperature" && c.values.temperature === 0;
      row.classList.toggle("idle", idle);
      if (idle) hint.textContent = "No effect at temperature 0.";
    };
    input.addEventListener("input", () => {
      c.values[s.name] = Number(input.value);
      c.values.preset = null;
      box.querySelectorAll(".lab-presets button").forEach((b) => b.setAttribute("aria-pressed", "false"));
      refreshColumn(col);
    });
    const row = el("div", { class: "lab-slider" }, el("label", {}, s.label, value), input, hint);
    return { s, input, show };
  });
  c.sliders = sliders;
  const presets = el("div", { class: "lab-presets", role: "group", "aria-label": "Start from" },
    ...PRESETS.map((p) => el("button", { type: "button", "aria-pressed": String(p.id === start), onclick: (e) => {
      c.values = presetValues(p.id);
      box.querySelectorAll(".lab-presets button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
      refreshColumn(col);
    } }, p.label)));
  const run = el("button", { class: "btn quiet lab-run", type: "button", onclick: () => runLab([col]) }, icon("i-play"), el("span", {}, `Run ${col.toUpperCase()}`));
  c.out = el("div", { class: "lab-out", "aria-live": "polite" }, el("p", { class: "none" }, "Run it to see the result here."));
  c.progress = new Progress(el("div", { class: "progress", hidden: "" }));
  box.replaceChildren(
    el("header", { class: "lab-col-head" }, el("span", { class: "lab-badge" }, col.toUpperCase()), presets),
    ...sliders.map((x) => x.input.closest(".lab-slider") || x.input.parentElement),
    run, c.progress.root, c.out);
  refreshColumn(col);
}

function refreshColumn(col) {
  const c = labState.cols[col];
  for (const { s, input, show } of c.sliders) {
    input.value = c.values[s.name];
    show();
  }
  // A result made with other settings is marked, so it's never mistaken for these.
  const box = $(`.lab-col[data-col="${col}"]`);
  box.classList.toggle("stale", !!c.ranWith && SLIDERS.some(({ name }) => c.ranWith[name] !== c.values[name]));
}

async function openLab() {
  if (!labState.defaults) {
    try {
      labState.defaults = await api("/api/lab");
    } catch (err) {
      $(".lab-cols").replaceChildren(el("p", { class: "error" }, err.message));
      return;
    }
  }
  if (!labState.ready) {
    buildColumn("a", "edit");
    buildColumn("b", "loose");
    setLabMode();
    labState.ready = true;
  }
  if (!$("#lab-text").value.trim()) fillFromEssay();
}

const LAB_PLACEHOLDER = {
  edit: "Paste one paragraph. A few mistakes make the differences easier to see.",
  draft: "What should the draft be about? One or two sentences is plenty; drafts here are short.",
};

function setLabMode() {
  $("#lab-text").placeholder = LAB_PLACEHOLDER[labMode()];
  $("#lab-fill").hidden = labMode() !== "edit";
  $(".lab-input-foot .aside").hidden = labMode() !== "edit";
}
$$('input[name="lab-mode"]').forEach((r) => r.addEventListener("change", () => {
  setLabMode();
  // Each mode starts A from Quill's own settings for that job.
  const a = labState.cols.a;
  if (a) {
    a.values = presetValues(labMode() === "edit" ? "edit" : "draft");
    $$('.lab-col[data-col="a"] .lab-presets button').forEach((b, i) => b.setAttribute("aria-pressed", String(PRESETS[i].id === (labMode() === "edit" ? "edit" : "draft"))));
    refreshColumn("a");
  }
}));

// The open essay's first paragraph with something to fix, or just its first paragraph.
function fillFromEssay() {
  const text = $("#body").value;
  const paras = paragraphSpans(text).map((p) => text.slice(p.start, p.end));
  if (!paras.length || labMode() !== "edit") return;
  const marked = state.suggestions.find((s) => s.paragraph != null && paras[s.paragraph]);
  $("#lab-text").value = marked ? paras[marked.paragraph] : paras[0];
}
$("#lab-fill").addEventListener("click", fillFromEssay);

async function runLab(cols) {
  const text = $("#lab-text").value.trim();
  if (!text) { $("#lab-text").focus(); return; }
  const mode = labMode();
  // One seed for every column in this run means the random draws match, so differences come
  // from the settings alone.
  const seed = $("#lab-same-seed").checked ? Math.floor(Math.random() * 1e6) : null;
  const buttons = $$(".lab-run, #lab-run-both");
  buttons.forEach((b) => { b.disabled = true; });
  try {
    for (const col of cols) { // one at a time: each run holds the model
      const c = labState.cols[col];
      const settings = { ...c.values, seed: seed ?? Math.floor(Math.random() * 1e6) };
      delete settings.preset;
      c.out.replaceChildren();
      c.progress.start(mode === "edit" ? "Reading the paragraph" : "Writing a short draft", { kind: `lab-${mode}`, expected: mode === "edit" ? 6 : 30 });
      try {
        c.result = await api("/api/lab", { method: "POST", body: { mode, text, settings } });
        c.ranWith = { ...settings };
        c.progress.finish();
        renderLabResult(col, text);
      } catch (err) {
        c.progress.fail(err.message);
      }
      refreshColumn(col);
    }
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}
$("#lab-run-both").addEventListener("click", () => runLab(["a", "b"]));
$("#lab-shade").addEventListener("change", (e) => $("#lab-view").classList.toggle("no-shade", !e.target.checked));

// A field's tokens as words you can click. Shading grows as the model's chance for the word drops.
function tokenRun(field, col) {
  const frag = document.createDocumentFragment();
  field.tokens.forEach((t, i) => {
    const tok = el("span", { class: "tok", tabindex: "0", "data-col": col, "data-f": field.id, "data-i": i,
      title: `${(t.p * 100).toFixed(1)}%` }, t.text);
    tok.style.setProperty("--doubt", Math.min(1, (1 - t.p) * 1.6).toFixed(3));
    if (t.cands.length && t.cands[0][0] !== t.tok) tok.classList.add("surprise");
    frag.append(tok);
  });
  return frag;
}

function renderLabResult(col, text) {
  const c = labState.cols[col];
  const r = c.result;
  r.fields.forEach((f, i) => { f.id = i; });
  const all = r.fields.flatMap((f) => f.tokens);
  const surprises = all.filter((t) => t.cands.length && t.cands[0][0] !== t.tok).length;
  const avg = all.length ? all.reduce((a, t) => a + t.p, 0) / all.length : 0;
  const stats = el("p", { class: "lab-stats" },
    `${r.seconds}s · ${all.length} word pieces · ${surprises} not the top pick · average chance ${Math.round(avg * 100)}%`);
  const byKey = (key, item) => r.fields.find((f) => f.key === key && f.item === item);
  // Clickable words when Ollama reported their chances, plain text when it didn't.
  const words = (field, fallback) => (r.chances && field ? tokenRun(field, col) : fallback);
  const parts = [r.chances ? stats : el("p", { class: "lab-stats" }, `${r.seconds}s`)];
  if (!r.chances) {
    parts.push(el("p", { class: "notice" }, "This model doesn't report its word chances through Ollama (it only gives them for the first word), so the words here can't be inspected. The settings still apply, so you can compare the two drafts."));
  }
  if (!r.complete) parts.push(el("p", { class: "notice" }, "The answer was cut off or didn't come back as valid JSON, which looser settings can cause."));
  if (r.mode === "edit") {
    const shown = r.suggestions.filter((s) => s.shown);
    let applied = text;
    for (const s of shown) applied = applied.replace(s.original, s.revised);
    const preview = el("p", { class: "lab-preview" });
    for (const seg of diffWords(text, applied)) {
      if (seg.type === "keep") preview.append(seg.del);
      else preview.append(seg.del.trim() ? el("del", {}, seg.del) : "", seg.ins.trim() ? el("ins", {}, seg.ins) : "");
    }
    parts.push(el("h4", {}, shown.length ? "The paragraph with these edits" : "No edits"), preview);
    r.suggestions.forEach((s, i) => {
      const revised = byKey("revised", i);
      const reason = byKey("reason", i);
      parts.push(el("div", { class: `lab-edit${s.shown ? "" : " hidden-edit"}` },
        el("span", { class: "lab-cat" }, s.category || "edit", s.shown ? null : " · Quill would hide this: the quote isn't in the paragraph or nothing changed"),
        el("p", { class: "lab-revised" }, words(revised, s.revised)),
        el("p", { class: "lab-reason" }, words(reason, s.reason))));
    });
  } else {
    const title = byKey("title", null);
    parts.push(el("h4", { class: "lab-title" }, words(title, r.title)));
    if (r.chances) r.fields.filter((f) => f.key === "paragraphs").forEach((f) => parts.push(el("p", { class: "lab-para" }, tokenRun(f, col))));
    else r.paragraphs.forEach((text) => parts.push(el("p", { class: "lab-para" }, text)));
  }
  c.out.replaceChildren(...parts);
}

// ---------- word inspector ----------

function openWordPop(tok) {
  const c = labState.cols[tok.dataset.col];
  const field = c.result.fields[Number(tok.dataset.f)];
  const t = field.tokens[Number(tok.dataset.i)];
  const settings = c.ranWith;
  const rows = applyCutoffs(t.cands, settings);
  const shown = (s) => JSON.stringify(s).slice(1, -1).replace(/^ /, "␣").replace(/ $/, "␣") || "∅";
  const pct = (x) => (x >= 0.1 ? `${(x * 100).toFixed(1)}%` : x > 0 ? `${(x * 100).toFixed(2)}%` : "0%");
  const why = { temperature: "temperature 0", top_k: "top_k", top_p: "top_p", min_p: "min_p" };
  const known = t.cands.reduce((a, [, p]) => a + p, 0);
  // Set through the style object: the page's security policy blocks inline style attributes.
  const bar = (p) => { const b = el("span", { class: "bar" }); b.style.setProperty("--w", `${Math.max(1, Math.round(p * 100))}%`); return b; };
  const pop = $("#word-pop");
  pop.replaceChildren(
    el("div", { class: "pop-head" },
      el("strong", {}, `“${t.text.trim() || t.text}”`),
      el("span", {}, ` was picked. The model gave it ${pct(t.p)}.`),
      el("button", { class: "icon-btn", "aria-label": "Close", onclick: closeWordPop }, icon("i-x"))),
    el("p", { class: "pop-sub" }, `With ${describeSettings(settings)}:`),
    el("table", { class: "cands" },
      el("thead", {}, el("tr", {}, el("th", {}, "Candidate"), el("th", {}, "Model"), el("th", {}, "After settings"), el("th", {}, ""))),
      el("tbody", {}, ...rows.map((r) => el("tr", { class: `${r.kept ? "kept" : "cut"}${r.token === t.tok ? " picked" : ""}` },
        el("td", { class: "cand" }, bar(r.p), shown(r.token)),
        el("td", {}, pct(r.p)),
        el("td", {}, r.kept ? pct(r.chance) : "—"),
        el("td", { class: "why" }, r.kept ? "kept" : `cut by ${why[r.cutBy]}`))))),
    el("p", { class: "pop-sub" }, known < 0.999
      ? `These 10 cover ${pct(known)} of the model's chances; the rest is spread over thousands of other words.`
      : "These 10 cover essentially all of the model's chances."),
  );
  pop.hidden = false;
  const r = tok.getBoundingClientRect();
  const below = r.bottom + 8 + pop.offsetHeight < innerHeight;
  pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8))}px`;
  pop.style.top = `${below ? r.bottom + 8 : Math.max(8, r.top - pop.offsetHeight - 8)}px`;
  $$(".tok.open").forEach((x) => x.classList.remove("open"));
  tok.classList.add("open");
  wordPopFrom = tok;
}
let wordPopFrom = null;
const describeSettings = (s) => (s.temperature === 0 ? "temperature 0" : `temperature ${s.temperature}, top_p ${s.top_p}, min_p ${s.min_p}, top_k ${s.top_k || "off"}`);

function closeWordPop(refocus = false) {
  if ($("#word-pop").hidden) return;
  $("#word-pop").hidden = true;
  $$(".tok.open").forEach((x) => x.classList.remove("open"));
  if (refocus === true) wordPopFrom?.focus();
}

$("#lab-view").addEventListener("click", (e) => {
  const tok = e.target.closest(".tok");
  if (tok) { e.stopPropagation(); openWordPop(tok); }
});
$("#lab-view").addEventListener("keydown", (e) => {
  const tok = e.target.closest(".tok");
  if (tok && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openWordPop(tok); }
});
document.addEventListener("click", (e) => { if (!e.target.closest("#word-pop")) closeWordPop(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeWordPop(true); });
addEventListener("resize", () => closeWordPop());

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
setCollapsed(storage("quill-side") === "collapsed");
state.token = storage("quill-token");
state.token ? showApp() : signOut();
