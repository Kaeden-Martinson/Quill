const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const state = {
  token: null,
  draftId: null,
  lastSaved: "",
  openVersion: null,
  suggestions: [], // {id, original, revised, reason, category, card}
  run: null,       // AbortController for the review in progress
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
const overlayDrawer = () => matchMedia("(max-width: 1279px)").matches;

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
  btn.replaceChildren(icon(dark ? "i-sun" : "i-moon"));
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
  api("/api/me").then(({ name }) => {
    $("#account-name").textContent = name;
    $("#account-username").value = name;
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
$("#logout-phone").addEventListener("click", logout);

async function refreshStatus() {
  const status = $("#model-status");
  try {
    const s = await api("/api/status");
    status.className = `status ${s.model_ready ? "ready" : "down"}`;
    status.title = s.model_ready ? `Model ${s.model} is ready` : `Model ${s.model} is offline`;
    status.querySelector(".status-text").textContent = s.model_ready ? s.model : "Model offline";
  } catch {
    status.className = "status down";
    status.querySelector(".status-text").textContent = "Server unreachable";
  }
}

// ---------- views, drawer, tabs ----------

function setView(view) {
  $("#write-view").hidden = view !== "write";
  $("#voice-view").hidden = view !== "voice";
  $("#app-view").classList.toggle("voice-mode", view === "voice");
  $$("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $(".crumb-root").textContent = view === "voice" ? "Settings" : "Essays";
  updateCrumb();
  closeDrawer();
}

$$("[data-view]").forEach((b) => b.addEventListener("click", () => {
  // On narrow screens the Essays button opens the essay list instead.
  if (b.dataset.view === "write" && b.classList.contains("rail-btn") && overlayDrawer() && !$("#write-view").hidden) {
    toggleDrawer();
    return;
  }
  setView(b.dataset.view);
}));

let drawerOpener = null;

function toggleDrawer(open = !$("#app-view").classList.contains("drawer-open")) {
  const overlay = open && overlayDrawer();
  const wasOpen = $("#app-view").classList.contains("drawer-open");
  $("#app-view").classList.toggle("drawer-open", overlay);
  $("#scrim").hidden = !overlay;
  // While the drawer covers the page, everything behind it is inert: keyboard and screen-reader
  // focus stay inside the drawer instead of wandering into content you can't see.
  for (const behind of [".main", ".rail"]) $(behind).inert = overlay;
  if (overlay && !wasOpen) {
    drawerOpener = document.activeElement;
    $("#close-drawer").focus();
  } else if (!overlay && wasOpen) {
    if (drawerOpener?.isConnected && !drawerOpener.closest("[inert]")) drawerOpener.focus();
    drawerOpener = null;
  }
}
const closeDrawer = () => toggleDrawer(false);
$("#open-drawer").addEventListener("click", () => toggleDrawer(true));
$("#close-drawer").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);
window.addEventListener("resize", () => { if (!overlayDrawer()) closeDrawer(); });

function setTab(name) {
  $$(".tab").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1; // one tab stop for the whole tab list; arrows move within it
  });
  $$(".tab-panel").forEach((p) => { p.hidden = p.dataset.panel !== name; });
}
$$(".tab").forEach((t) => t.addEventListener("click", () => setTab(t.dataset.tab)));

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
  const essay = !$("#write-view").hidden;
  $("#crumb-title").textContent = essay
    ? (state.draftId ? $("#title").value.trim() || "Untitled essay" : "No essay open")
    : "Voice and account";
}

function setDraftControls(enabled) {
  for (const id of ["#review", "#review-phone", "#overview", "#save", "#export", "#export-docx", "#delete-draft"]) $(id).disabled = !enabled;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && state.draftId) {
    e.preventDefault();
    saveVersion("Manual save");
  }
});

// ---------- drafts ----------

async function loadDrafts() {
  const drafts = await api("/api/drafts");
  $("#draft-list").replaceChildren(
    ...(drafts.length
      ? drafts.map((d) =>
          el("li", {},
            el("button", { class: d.id === state.draftId ? "active" : "", onclick: () => openDraft(d.id) },
              el("span", { class: "d-title" }, d.title),
              el("span", { class: "d-meta" }, `${d.versions} version${d.versions === 1 ? "" : "s"} · ${fmtDate(d.updated)}`))))
      : [el("li", { class: "empty-list" }, "No essays yet.")])
  );
}

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
  $("#version-list").replaceChildren(
    ...[...versions].reverse().map((v) =>
      el("li", {},
        el("button", { onclick: () => viewVersion(v.id) },
          el("span", { class: "v-note" }, v.note || "Autosave"),
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

// ---------- editor: auto-grow and highlights ----------

function onBodyChange() {
  const body = $("#body");
  const words = body.value.trim().split(/\s+/).filter(Boolean).length;
  $("#word-count").textContent = `${words.toLocaleString()} word${words === 1 ? "" : "s"}`;
  // Grow with the content so the textarea never scrolls and stays aligned with the backdrop.
  body.style.height = "auto";
  body.style.height = `${body.scrollHeight}px`;
  renderHighlights();
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

function renderHighlights() {
  const text = $("#body").value;
  const nodes = [];
  let at = 0;
  for (const { start, end, s } of suggestionRanges()) {
    nodes.push(text.slice(at, start));
    nodes.push(el("mark", { "data-id": s.id, class: s.revised == null ? "generic" : "" }, text.slice(start, end)));
    at = end;
  }
  // Trailing newline keeps the last empty line the same height as in the textarea.
  nodes.push(text.slice(at) + "\n");
  $("#backdrop").replaceChildren(...nodes);
}

function setActive(id, on) {
  $(`#backdrop mark[data-id="${id}"]`)?.classList.toggle("active", on);
}

// Clicking highlighted text in the draft brings up its suggestion.
$("#body").addEventListener("click", () => {
  const caret = $("#body").selectionStart;
  const hit = suggestionRanges().find((r) => caret >= r.start && caret <= r.end);
  if (!hit) return;
  setTab("edits");
  const card = hit.s.card;
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  card.classList.add("flash");
  setActive(hit.s.id, true);
  setTimeout(() => { card.classList.remove("flash"); setActive(hit.s.id, false); }, 1600);
});

// ---------- review (streamed) ----------

function emptyHint(html) {
  const p = el("p", { class: "hint" });
  p.innerHTML = html; // static strings only
  return p;
}

function clearFeedback() {
  state.suggestions = [];
  $("#suggestion-list").replaceChildren(
    emptyHint("Run <strong>Review draft</strong> for edits on each paragraph. Accept the ones you agree with; nothing changes until you do.")
  );
  $("#voice-notes").replaceChildren();
  $("#overview-panel").replaceChildren();
  $("#progress").hidden = true;
  updateCounts();
  renderHighlights();
}

function setProgress(text, fraction = null) {
  const p = $("#progress");
  p.hidden = false;
  const fill = el("span");
  const bar = el("div", { class: fraction == null ? "bar indeterminate" : "bar" }, fill);
  if (fraction != null) fill.style.width = `${Math.max(4, Math.round(fraction * 100))}%`;
  p.replaceChildren(el("div", {}, text), bar);
}

function setProgressMessage(text) {
  $("#progress").hidden = false;
  $("#progress").replaceChildren(el("div", {}, text));
}

function queueText(position) {
  return position === 1
    ? "You're next. Someone else's essay is being reviewed."
    : `You're ${ordinal(position)} in line. Others are using Quill right now.`;
}

function updateCounts() {
  const n = state.suggestions.length;
  $("#edit-count").textContent = n || "";
  const jump = $("#jump-suggestions");
  jump.hidden = n === 0;
  jump.querySelector("span").textContent = `${n}`;
  jump.setAttribute("aria-label", `${n} suggestion${n === 1 ? "" : "s"}`);
}

function addSuggestions(items) {
  const list = $("#suggestion-list");
  list.querySelector(".hint")?.remove();
  for (const item of items) {
    const s = { ...item, id: nextId++ };
    s.card = suggestionCard(s);
    state.suggestions.push(s);
    list.append(s.card);
  }
  updateCounts();
  renderHighlights();
}

function removeSuggestion(s) {
  state.suggestions = state.suggestions.filter((x) => x !== s);
  s.card.remove();
  if (!state.suggestions.length && !state.run) {
    $("#suggestion-list").replaceChildren(emptyHint("All suggestions handled. Run <strong>Review draft</strong> again after you revise."));
  }
  updateCounts();
  renderHighlights();
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
    if (!b.dataset.icon) b.dataset.icon = b.querySelector("use").getAttribute("href").slice(1);
    if (!b.dataset.label) b.dataset.label = b.querySelector("span").textContent;
    b.querySelector("svg").replaceWith(icon(isActive ? "i-stop" : b.dataset.icon));
    b.querySelector("span").textContent = isActive ? "Stop" : b.dataset.label;
  }
}

async function runStream(trigger, path, onEvent) {
  if (state.run) { stopRun(); return; } // second click = Stop
  const body = $("#body").value.trim();
  if (!body) return;
  await saveVersion("Before review");
  const run = (state.run = new AbortController());
  setRunning(trigger);
  setProgress("Starting");
  let failed = false;
  try {
    await stream(path, { body, goal: $("#goal").value }, (event) => {
      if (event.type === "queue") setProgress(queueText(event.position));
      else if (event.type === "error") { failed = true; setProgressMessage(event.message); }
      else onEvent(event);
    }, run.signal);
    if (!failed) $("#progress").hidden = true;
  } catch (err) {
    setProgressMessage(err.name === "AbortError" ? "Stopped." : err.message);
  } finally {
    if (state.run === run) state.run = null;
    setRunning(null);
  }
}

function startReview(trigger) {
  if (!state.run) {
    setTab("edits");
    state.suggestions.forEach((s) => s.card.remove());
    state.suggestions = [];
    $("#suggestion-list").replaceChildren();
    $("#voice-notes").replaceChildren();
    updateCounts();
    renderHighlights();
  }
  let modelCount = 0;
  runStream(trigger, "/api/review", (event) => {
    if (event.type === "instant") {
      $("#voice-notes").replaceChildren(...event.voice_notes.map((n) => el("div", { class: "voice-note" }, icon("i-alert"), el("span", {}, n))));
      addSuggestions(event.suggestions);
    } else if (event.type === "start") {
      setProgress(`Reviewing paragraph 1 of ${event.total}`, 0);
    } else if (event.type === "paragraph") {
      modelCount += event.suggestions.length;
      addSuggestions(event.suggestions.map((s) => ({ ...s, paragraph: event.index })));
      const done = event.index + 1;
      if (done < event.total) setProgress(`Reviewing paragraph ${done + 1} of ${event.total}`, done / event.total);
    } else if (event.type === "done" && state.suggestions.length === 0) {
      $("#suggestion-list").replaceChildren(emptyHint("No suggestions. This draft reads well as it is."));
    } else if (event.type === "done" && modelCount === 0) {
      $("#suggestion-list").prepend(emptyHint("No line edits needed beyond the notes above."));
    }
  });
}

$("#review").addEventListener("click", () => startReview("#review"));
$("#review-phone").addEventListener("click", () => startReview("#review-phone"));

$("#overview").addEventListener("click", () => {
  if (!state.run) $("#overview-panel").replaceChildren();
  let notice = null;
  runStream("#overview", "/api/overview", (event) => {
    if (event.type === "start") setProgress("Reading the whole essay");
    else if (event.type === "notice") notice = event.message;
    else if (event.type === "overview") {
      renderOverview(event.overview);
      if (notice) $("#overview-panel").prepend(el("div", { class: "voice-note" }, icon("i-alert"), el("span", {}, notice)));
    }
  });
});

function renderOverview(o) {
  if (!o) {
    $("#overview-panel").replaceChildren(el("p", { class: "error" }, "Couldn't read the feedback. Try again."));
    return;
  }
  const ratingClass = (r) => r.replace(/\s+/g, "-");
  $("#overview-panel").replaceChildren(
    el("div", { class: "ov-priority" }, el("span", { class: "ov-label" }, "Top priority"), el("p", {}, o.top_priority)),
    el("div", { class: "ov-list" },
      ...o.comments.map((c) =>
        el("div", { class: "ov-item" },
          el("div", { class: "ov-head" }, el("strong", {}, c.aspect), el("span", { class: `rating ${ratingClass(c.rating)}` }, c.rating)),
          el("p", {}, c.comment))),
      el("div", { class: "ov-item" },
        el("div", { class: "ov-head" }, el("strong", {}, "Keep this"), el("span", { class: "rating strong" }, "working")),
        el("p", {}, o.strongest_part)),
    ),
  );
}

function suggestionCard(s) {
  const card = el("article", {
    class: "sg",
    onmouseenter: () => setActive(s.id, true),
    onmouseleave: () => setActive(s.id, false),
  });
  const done = (accepted) => {
    const { card: _card, id: _id, ...payload } = s;
    api("/api/feedback", { method: "POST", body: { ...payload, draft_id: state.draftId, revised: s.revised ?? "", accepted } }).catch(() => {});
    removeSuggestion(s);
  };
  const button = (label, iconName, onclick, cls = "") =>
    el("button", { class: `btn sm ${cls}`, onclick }, icon(iconName), label);
  const actions = s.revised == null
    ? [button("Show me", "i-locate", () => highlight(s)),
       button("Dismiss", "i-x", () => removeSuggestion(s), "ghost")]
    : [button("Accept", "i-check", () => { if (applyEdit(s)) done(true); }, "primary"),
       button("Reject", "i-x", () => done(false)),
       button("Find", "i-locate", () => highlight(s), "ghost")];
  const category = (s.category || "").toLowerCase();
  const label = category.charAt(0).toUpperCase() + category.slice(1);
  const parts = [
    el("span", { class: "cat" }, icon(`c-${category.replace(/\s+/g, "-")}`), label),
    // A flagged phrase isn't a deletion, so it's quoted rather than struck through.
    el("span", { class: s.revised == null ? "quote" : "old" }, s.original),
    s.revised != null ? el("span", { class: "new" }, s.revised) : null,
    el("p", { class: "why" }, s.reason),
    el("div", { class: "row" }, ...actions),
  ];
  card.append(...parts.filter(Boolean));
  return card;
}

function highlight(s) {
  const body = $("#body");
  const at = locate(s, $("#body").value);
  if (at === -1) return false;
  body.focus({ preventScroll: true });
  body.setSelectionRange(at, at + s.original.length);
  // The textarea doesn't scroll itself, so bring the selected line into view.
  $(`#backdrop mark[data-id="${s.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}

function applyEdit(s) {
  const at = locate(s, $("#body").value);
  if (at === -1) {
    alert("That text has changed since the review, or now appears more than once, so this suggestion can't be applied automatically. Use Find, or edit it by hand.");
    return false;
  }
  replaceRange(at, at + s.original.length, s.revised);
  return true;
}

// ---------- voice profile ----------

function addSample(text = "") {
  const t = el("textarea", { placeholder: "Paste something you wrote, like an old essay, a blog post or a long email", "aria-label": "Writing sample" });
  t.value = text;
  $("#samples").append(t);
}
$("#add-sample").addEventListener("click", () => addSample());

async function loadProfile() {
  const p = await api("/api/profile");
  $("#samples").replaceChildren();
  (p.samples.length ? p.samples : ["", "", ""]).forEach(addSample);
  $("#voice-summary").textContent = p.samples.length ? p.voice : "Nothing yet. Add samples above.";
}

$("#save-profile").addEventListener("click", async () => {
  const samples = $$("#samples textarea").map((t) => t.value).filter((t) => t.trim());
  if (!samples.length) { $("#profile-status").textContent = "Add at least one sample."; return; }
  try {
    const p = await api("/api/profile", { method: "PUT", body: { samples } });
    $("#voice-summary").textContent = p.voice;
    $("#profile-status").textContent = "Saved.";
  } catch (err) {
    $("#profile-status").textContent = err.message;
  }
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

state.token = storage("quill-token");
state.token ? showApp() : signOut();
