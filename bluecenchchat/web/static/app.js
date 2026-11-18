/* Blue Cench Chat web app - phones, tablets, watches. Talks only to the Blue Cench Chat PC on the same network. */
"use strict";

const S = {
  me: null, tab: "chats", chat: null, convs: [], msgs: [], replyTo: null, typing: {}, nearby: null,
  transfers: [], tmap: {}, people: "accepted", peopleList: [], notifs: [], q: "", ws: null, contact: null,
  feed: [], notes: null, profile: null, tab0: "home",
};
/* theme: Instagram white by default, dark on request (remembered on this device) */
function getTheme() { try { return localStorage.getItem("bcc-theme") || "light"; } catch (_) { return "light"; } }
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", { dark: "#000000", midnight: "#060E24" }[t] || "#FFFFFF");
}
function toggleTheme() {
  const order = ["light", "dark", "midnight"];
  const t = order[(order.indexOf(getTheme()) + 1) % order.length];
  try { localStorage.setItem("bcc-theme", t); } catch (_) { /* private mode */ }
  applyTheme(t); render();
}
applyTheme(getTheme());
const root = document.getElementById("root");
const wide = window.matchMedia("(min-width: 760px)");
const REACTIONS = ["thumbs-up", "heart", "laugh", "party-popper", "check", "flame"];
const QUICK = ["OK", "Yes", "No", "On my way", "Thanks!", "Call you later"];

/* ------------------------------------------------------------------ helpers */
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.style.cssText = v;  // CSSOM is allowed by the strict CSP
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function icon(name, cls) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ic " + (cls || ""));
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "/static/icons.svg#i-" + name);
  svg.append(use);
  return svg;
}
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", credentials: "same-origin", headers: { "X-BlueCenchChat": "1" } };
  if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  if (init.method === "GET") delete init.headers["X-BlueCenchChat"];
  const r = await fetch(path, init);
  if (r.status === 401) { showPair(); throw new Error("Not paired"); }
  let data = null;
  try { data = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) throw new Error((data && data.detail) || ("Error " + r.status));
  return data;
}
const post = (p, body) => api(p, { method: "POST", body: body || {} });
async function postForm(path, form) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "X-BlueCenchChat": "1" }, body: form });
  if (r.status === 401) { showPair(); throw new Error("Not paired"); }
  let data = null;
  try { data = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) throw new Error((data && data.detail) || ("Error " + r.status));
  return data;
}
const tick = (on) => on ? h("span", { class: "tick", title: "Verified" }, icon("badge-check", "sm")) : null;
function toast(text, tone) {
  const host = document.getElementById("toast-host");
  const ic = { ok: ["circle-check", "ok"], err: ["circle-alert", "bad"], warn: ["triangle-alert", "warn"] }[tone] || ["info", "cyan"];
  const t = h("div", { class: "toast" }, h("span", { class: ic[1] }, icon(ic[0])), h("span", {}, text));
  host.append(t);
  setTimeout(() => t.remove(), 3600);
}
const run = (p, okMsg) => p.then((r) => { if (okMsg) toast(okMsg, "ok"); return r; }).catch((e) => { if (e.message !== "Not paired") toast(e.message, "err"); });
function size(n) {
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return i === 0 ? `${Math.round(n)} B` : `${n.toFixed(1)} ${u[i]}`;
}
function ago(ts) {
  if (!ts) return "never";
  const d = Date.now() / 1000 - ts;
  if (d < 45) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  const dt = new Date(ts * 1000), now = new Date();
  if (dt.toDateString() === now.toDateString()) return dt.toTimeString().slice(0, 5);
  if (d < 7 * 86400) return dt.toLocaleDateString(undefined, { weekday: "short" }) + " " + dt.toTimeString().slice(0, 5);
  return dt.toLocaleDateString();
}
function dur(s) {
  if (s === null || s === undefined) return "--";
  s = Math.round(s);
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
const COLORS = ["#2F7BFF", "#22D3EE", "#8B5CF6", "#F59E0B", "#10B981", "#EF4444", "#EC4899", "#14B8A6"];
function avatar(c, cls, online) {
  const seed = (c.uid || c.name || "x");
  let sum = 0; for (const ch of seed) sum += ch.charCodeAt(0);
  const el = h("div", { class: "av " + (cls || ""), style: `background-color:${COLORS[sum % COLORS.length]}` });
  if (c.has_avatar) el.style.backgroundImage = `url(/api/avatar/${c.id})`;
  else el.append((c.name || "?").split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase() || "?");
  if (online !== undefined) el.append(h("i", { class: "dot" + (online ? " on" : "") }));
  return el;
}
function fileIcon(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "heic"].includes(ext)) return "image";
  if (["mp4", "mov", "mkv", "avi", "webm"].includes(ext)) return "video";
  if (["mp3", "wav", "m4a", "aac", "flac", "ogg"].includes(ext)) return "music";
  if (["zip", "rar", "7z", "tar", "gz"].includes(ext)) return "file-archive";
  if (["exe", "msi", "apk"].includes(ext)) return "package";
  if (/files\)$/.test(name)) return "folder";
  return ["pdf", "doc", "docx", "txt", "xls", "xlsx", "ppt", "pptx", "csv"].includes(ext) ? "file-text" : "file";
}
function deviceName() {
  const ua = navigator.userAgent;
  if (/Watch|Wear OS|wearable/i.test(ua) || Math.min(screen.width, screen.height) < 330) return "Watch";
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "iPad";
  if (/iPhone/.test(ua)) return "iPhone";
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? "Android phone" : "Android tablet";
  return "Browser";
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ------------------------------------------------------------------ pairing */
function showPair(err) {
  if (S.ws) { try { S.ws.close(); } catch (_) { /* ignore */ } S.ws = null; }
  root.className = "";
  const code = h("input", { class: "code-input", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6",
    placeholder: "000000", "aria-label": "Pairing code" });
  const name = h("input", { class: "field", value: deviceName(), maxlength: "60", "aria-label": "Device name" });
  const msg = h("div", { class: "bad" }, err || "");
  const go = async (token) => {
    msg.textContent = "";
    try {
      await post("/api/pair", token ? { token, name: name.value } : { code: code.value, name: name.value });
      history.replaceState(null, "", "/");
      start();
    } catch (e) { msg.textContent = e.message; }
  };
  const btn = h("button", { class: "btn primary block", onclick: () => go() }, icon("link"), "Pair this device");
  code.addEventListener("input", () => { code.value = code.value.replace(/\D/g, ""); if (code.value.length === 6) go(); });
  root.replaceChildren(h("div", { class: "pair" }, h("div", { class: "pair-card" },
    h("img", { src: "/static/icon-192.png", alt: "Blue Cench Chat" }),
    h("h1", {}, "Connect to Blue Cench Chat"),
    h("div", { class: "muted" }, "Enter the 6-digit code shown on your PC under Phones & Tablets."),
    code, h("div", { class: "faint" }, "Name this device"), name, h("div", { style: "height:12px" }), btn, msg,
    h("ol", { class: "steps hide-watch" },
      h("li", {}, "Your phone and PC must be on the same Wi-Fi or the PC's Mobile Hotspot."),
      h("li", {}, "Bluetooth stays on the PC - this device controls it over Wi-Fi."),
      h("li", {}, "Tip: add this page to your home screen to use it like an app.")))));
  const m = location.hash.match(/pair=([A-Za-z0-9_-]+)/);
  if (m && !err) go(m[1]); else code.focus();
}

/* ------------------------------------------------------------------ shell */
const TABS = [["home", "Home", "house"], ["chats", "Chats", "message-square"], ["people", "People", "users"],
  ["nearby", "Nearby", "radar"], ["files", "Files", "arrow-left-right"], ["more", "Profile", "user"]];

function badgeFor(tab) {
  const m = S.me || {};
  return { chats: m.unread, people: m.requests, files: m.offers, more: m.alerts }[tab] || 0;
}

function render() {
  root.className = "";
  const nav = h("nav", { class: "nav" + (!wide.matches && S.tab === "chats" && S.chat ? " hidden" : ""), "aria-label": "Sections" },
    h("div", { class: "brand" }, h("img", { src: "/static/icon-192.png", alt: "" }), h("span", { class: "hide-watch" }, wide.matches && innerWidth >= 1180 ? "Blue Cench Chat" : "")),
    TABS.map(([key, label, ic]) => {
      const n = badgeFor(key);
      return h("button", { class: S.tab === key ? "on" : "", onclick: () => switchTab(key), "aria-label": label },
        icon(ic), h("span", { class: "lbl" }, label), n ? h("span", { class: "badge" }, n > 99 ? "99+" : n) : null);
    }));
  const main = h("div", { class: "main" });
  if (S.tab === "chats") {
    if (wide.matches || !S.chat) main.append(chatList());
    if (S.chat) main.append(chatView());
    else if (wide.matches) main.append(h("div", { class: "detail" }, h("div", { class: "empty", style: "margin:auto" },
      icon("message-square"), h("div", {}, "Choose a conversation"),
      h("div", { class: "faint" }, "Messages go from this device to your PC over Wi-Fi, then to your contact over Bluetooth or the local network."))));
  } else if (S.tab === "home") main.append(homeView());
  else if (S.tab === "people") main.append(peopleView());
  else if (S.tab === "nearby") main.append(nearbyView());
  else if (S.tab === "files") main.append(filesView());
  else main.append(moreView());
  root.replaceChildren(h("div", { class: "shell" }, main, nav));
  if (S.chat) scrollChat(true);
}
function switchTab(tab) {
  S.tab = tab;
  if (tab !== "chats") S.chat = null;
  render();
  ({ home: loadHome, chats: loadConvs, people: loadPeople, nearby: loadNearby, files: loadTransfers,
    more: () => { loadNotifs(); loadProfile(); } })[tab]();
}
function topbar(title, ...extra) {
  return h("div", { class: "top" }, h("h1", {}, title), ...extra);
}

/* ------------------------------------------------------------------ chats */
function chatList() {
  const list = h("div", { class: "scroll", id: "convs" });
  const search = h("input", { placeholder: "Search", value: S.q, "aria-label": "Search conversations",
    oninput: (e) => { S.q = e.target.value; fillConvs(list); } });
  fillConvs(list);
  return h("section", { class: "panel list" }, topbar("Chats"),
    h("div", { style: "padding:10px 12px 0" }, h("label", { class: "search" }, icon("search", "sm"), search)), list);
}
function fillConvs(list) {
  list = list || document.getElementById("convs");
  if (!list) return;
  const q = S.q.trim().toLowerCase();
  const items = S.convs.filter((c) => !q || c.name.toLowerCase().includes(q) || c.username.toLowerCase().includes(q));
  if (!items.length) {
    list.replaceChildren(h("div", { class: "empty" }, icon("message-square"),
      h("div", {}, S.convs.length ? "No matches" : "No conversations yet"),
      h("div", { class: "faint" }, "Connect with someone from the Nearby tab.")));
    return;
  }
  list.replaceChildren(...items.map((c) => {
    const last = c.last;
    const prev = last ? (last.dir === "out" ? "You: " : "") + (last.kind === "file" ? "File: " : "") + last.body : "No messages yet";
    return h("div", { class: "row" + (S.chat === c.id ? " sel" : ""), onclick: () => openChat(c.id), role: "button" },
      avatar(c, "", c.online),
      h("div", { class: "grow" }, h("div", { class: "title" }, c.name, tick(c.tick)),
        h("div", { class: "sub" }, prev.replace(/\n/g, " "))),
      h("div", { class: "meta" }, h("span", { class: "faint" }, last ? ago(last.ts) : ""),
        c.unread ? h("span", { class: "count" }, c.unread) : null));
  }));
}
async function openChat(id) {
  S.tab = "chats";
  if (S.chat !== id) { S.chat = id; S.msgs = []; S.replyTo = null; }
  if (!wide.matches) history.pushState({ chat: id }, "");
  render();
  await Promise.all([loadMsgs(), loadContact(), loadTransfers(true)]);
  run(post(`/api/messages/${id}/read`)).then(loadMe);
}
function closeChat() { S.chat = null; render(); loadConvs(); }
window.addEventListener("popstate", () => { if (S.chat && !wide.matches) closeChat(); });

function chatView() {
  const c = S.contact && S.contact.id === S.chat ? S.contact : (S.convs.find((x) => x.id === S.chat) || { name: "", id: S.chat });
  const status = S.typing[S.chat] ? "typing..." : c.online ? `Online - ${c.transport}` : `Offline - last seen ${ago(c.last_seen)}`;
  const box = h("textarea", { rows: "1", placeholder: c.status === "accepted" ? "Message" : "Waiting for acceptance",
    disabled: c.status && c.status !== "accepted", "aria-label": "Message", id: "composer" });
  let typingSent = 0;
  box.addEventListener("input", () => {
    box.style.height = "auto"; box.style.height = Math.min(140, box.scrollHeight) + "px";
    if (Date.now() - typingSent > 3000 && box.value) { typingSent = Date.now(); post(`/api/messages/${S.chat}/typing`, { on: true }).catch(() => {}); }
  });
  box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && wide.matches) { e.preventDefault(); send(box); } });
  const file = h("input", { type: "file", multiple: true, class: "hidden", onchange: (e) => upload(e.target.files) });
  const reply = S.replyTo ? h("div", { class: "replybar" }, icon("reply", "sm"),
    h("span", {}, "Replying: " + (S.replyTo.preview || S.replyTo.body)), h("button", { class: "icon-btn", onclick: () => { S.replyTo = null; render(); }, "aria-label": "Cancel reply" }, icon("x", "sm"))) : null;
  return h("section", { class: wide.matches ? "detail" : "panel" }, h("div", { class: "chat" },
    h("div", { class: "top" },
      h("button", { class: "icon-btn back", onclick: () => history.length > 1 && !wide.matches ? history.back() : closeChat(), "aria-label": "Back" }, icon("chevron-left")),
      avatar(c, "sm", c.online),
      h("div", { class: "who" }, h("b", {}, c.name, tick(c.tick), c.verified ? h("span", { class: "ok", title: "Safety number checked" }, icon("shield-check", "sm")) : null),
        h("span", { id: "chat-status" }, status)),
      h("button", { class: "icon-btn", onclick: () => toast("Calls ring on your PC - answer them in the Blue Cench Chat app there.", "warn"), "aria-label": "Call" }, icon("phone")),
      h("button", { class: "icon-btn", onclick: () => contactSheet(c), "aria-label": "Contact options" }, icon("ellipsis-vertical"))),
    h("div", { class: "msgs", id: "msgs" }, msgNodes()),
    h("div", { class: "typing", id: "typing" }, S.typing[S.chat] ? signal(c.name) : ""),
    c.status === "accepted" ? h("div", { class: "quick" }, QUICK.map((q) => h("button", { onclick: () => sendText(q) }, q))) : null,
    reply,
    h("div", { class: "composer" },
      h("button", { class: "icon-btn attach", onclick: () => file.click(), "aria-label": "Send files", disabled: c.status !== "accepted" }, icon("paperclip")),
      file, box,
      h("button", { class: "icon-btn mic", id: "mic", onclick: () => toggleRecord(), "aria-label": "Record a voice message", disabled: c.status !== "accepted" }, icon("mic")),
      h("button", { class: "send", onclick: () => send(box), "aria-label": "Send" }, icon("send")))));
}
/* Blue Cench "signal" typing indicator: three beams pulsing out from the sender */
function signal(name) {
  return h("span", { class: "signal", role: "status" }, h("i", {}), h("i", {}), h("i", {}), h("b", {}, name), " is writing");
}
/* ---- voice messages: record on the phone, upload 8 kHz 16-bit PCM ---- */
const REC = { on: false };
async function toggleRecord() {
  const btn = document.getElementById("mic");
  if (REC.on) { stopRecord(true); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { toast("This browser can't record audio", "err"); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    proc.onaudioprocess = (e) => { if (REC.on) chunks.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
    src.connect(proc); proc.connect(ctx.destination);
    Object.assign(REC, { on: true, stream, ctx, proc, src, chunks, t0: Date.now(), cid: S.chat });
    if (btn) btn.classList.add("rec");
    REC.timer = setInterval(() => {
      const s = Math.floor((Date.now() - REC.t0) / 1000);
      const b = document.getElementById("mic");
      if (b) b.setAttribute("data-t", `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
      if (s >= 90) stopRecord(true);
    }, 250);
    toast("Recording - tap the mic again to send");
  } catch (e) { toast("Microphone blocked: " + e.message, "err"); }
}
function stopRecord(sendIt) {
  if (!REC.on) return;
  REC.on = false; clearInterval(REC.timer);
  const btn = document.getElementById("mic"); if (btn) { btn.classList.remove("rec"); btn.removeAttribute("data-t"); }
  try { REC.src.disconnect(); REC.proc.disconnect(); } catch (_) { /* already closed */ }
  REC.stream.getTracks().forEach((t) => t.stop());
  const rate = REC.ctx.sampleRate; REC.ctx.close();
  if (!sendIt) return;
  const total = REC.chunks.reduce((n, c) => n + c.length, 0);
  const all = new Float32Array(total); let o = 0; for (const c of REC.chunks) { all.set(c, o); o += c.length; }
  const step = rate / 8000, n = Math.floor(total / step), pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * step), b = Math.max(a + 1, Math.floor((i + 1) * step)); let s = 0;
    for (let j = a; j < b; j++) s += all[j];
    pcm[i] = Math.max(-32768, Math.min(32767, Math.round((s / (b - a)) * 32767)));
  }
  if (n < 4000) { toast("Too short - record at least half a second", "warn"); return; }
  fetch(`/api/messages/${REC.cid}/voice`, { method: "POST", credentials: "same-origin",
    headers: { "X-BlueCenchChat": "1", "Content-Type": "application/octet-stream" }, body: pcm.buffer })
    .then((r) => r.ok ? r.json() : r.json().then((d) => { throw new Error(d.detail || ("Error " + r.status)); }))
    .then((m) => { if (!S.msgs.find((x) => x.id === m.id)) S.msgs.push(m); fillMsgs(); scrollChat(true); })
    .catch((e) => toast(e.message, "err"));
}
function voiceBubble(m) {
  let audio = null;
  const secs = parseFloat(m.body) || 0;
  const label = h("span", { class: "vt" }, `${Math.floor(secs / 60)}:${String(Math.round(secs % 60)).padStart(2, "0")}`);
  let seed = 0; for (const ch of m.id) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
  const bars = h("span", { class: "wave" }, Array.from({ length: 28 }, () => {
    seed = (seed * 1103515245 + 12345) >>> 0;
    const el = h("i", {}); el.style.height = (25 + (seed % 75)) + "%"; return el;
  }));
  const btn = h("button", { class: "vplay", "aria-label": "Play voice message", onclick: (e) => {
    e.stopPropagation();
    if (!audio) {
      audio = new Audio(`/api/voice/${m.id}`);
      audio.addEventListener("timeupdate", () => {
        const p = audio.currentTime / (audio.duration || secs || 1);
        [...bars.children].forEach((b, i) => b.classList.toggle("on", i / bars.children.length < p));
      });
      audio.addEventListener("ended", () => { btn.replaceChildren(icon("play")); [...bars.children].forEach((b) => b.classList.remove("on")); });
    }
    if (audio.paused) { audio.play(); btn.replaceChildren(icon("pause")); } else { audio.pause(); btn.replaceChildren(icon("play")); }
  } }, icon("play"));
  return h("span", { class: "voice" }, btn, bars, label);
}

function msgNodes() {
  const out = [];
  let day = "";
  for (const m of S.msgs) {
    const d = new Date(m.ts * 1000).toDateString();
    if (d !== day) { day = d; out.push(h("div", { class: "day" }, new Date(m.ts * 1000).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }))); }
    if (m.kind === "file" && m.transfer_id) {
      const t = S.tmap[m.transfer_id];
      out.push(h("div", { class: "filecard " + m.dir }, t ? tcard(t, true) : h("div", { class: "card" }, icon(fileIcon(m.body)), " ", m.body)));
      continue;
    }
    if (m.kind === "call") {
      out.push(h("div", { class: "callrow" + (m.body.startsWith("Missed") ? " missed" : "") },
        icon(m.body.includes("Video") ? "video" : "phone", "sm"), m.body, h("span", { class: "faint" }, new Date(m.ts * 1000).toTimeString().slice(0, 5))));
      continue;
    }
    const quoted = m.reply_to ? S.msgs.find((x) => x.id === m.reply_to) : null;
    const st = { queued: "clock", sent: "check", delivered: "check-check", read: "check-check", failed: "circle-alert", relayed: "radio" }[m.status];
    out.push(h("div", { class: `b ${m.dir}${m.reaction ? " has-rx" : ""}`, onclick: () => msgSheet(m) },
      m.reply_to ? h("div", { class: "q" }, quoted ? (quoted.preview || quoted.body).slice(0, 120) : "Earlier message") : null,
      m.kind === "voice" ? voiceBubble(m) : m.body,
      h("div", { class: "t" }, new Date(m.ts * 1000).toTimeString().slice(0, 5),
        m.dir === "out" && st ? h("span", { class: m.status === "read" ? "read" : "", title: m.status }, icon(st)) : null),
      m.reaction ? h("span", { class: "rx" }, icon(m.reaction)) : null));
  }
  if (!out.length) out.push(h("div", { class: "empty" }, icon("lock"), h("div", {}, "Messages are end-to-end encrypted between the two PCs.")));
  return out;
}
function scrollChat(force) {
  const el = document.getElementById("msgs");
  if (el && (force || el.scrollHeight - el.scrollTop - el.clientHeight < 160)) el.scrollTop = el.scrollHeight;
}
function fillMsgs() {
  const el = document.getElementById("msgs");
  if (!el) return;
  const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
  el.replaceChildren(...msgNodes());
  if (stick) el.scrollTop = el.scrollHeight;
}
function send(box) { const t = box.value.trim(); if (!t) return; box.value = ""; box.style.height = "auto"; sendText(t); }
async function sendText(text) {
  const reply = S.replyTo ? S.replyTo.id : null;
  S.replyTo = null;
  document.querySelector(".replybar")?.remove();
  try {
    const m = await api(`/api/messages/${S.chat}`, { method: "POST", body: { text, reply_to: reply } });
    if (!S.msgs.find((x) => x.id === m.id)) S.msgs.push(m);
    fillMsgs(); scrollChat(true);
  } catch (e) { toast(e.message, "err"); }
}
function upload(files) {
  if (!files || !files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", `/api/send/${S.chat}`);
  xhr.setRequestHeader("X-BlueCenchChat", "1");
  const t = h("div", { class: "toast" }, icon("upload"), h("span", {}, "Uploading to PC 0%"));
  document.getElementById("toast-host").append(t);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) t.lastChild.textContent = `Uploading to PC ${Math.round(e.loaded / e.total * 100)}%`; };
  xhr.onload = () => {
    t.remove();
    if (xhr.status === 200) { toast("Sent to your PC - waiting for your contact to accept", "ok"); loadTransfers(true); loadMsgs(); }
    else { let d = "Upload failed"; try { d = JSON.parse(xhr.responseText).detail || d; } catch (_) { /* */ } toast(d, "err"); }
  };
  xhr.onerror = () => { t.remove(); toast("Upload failed - check the Wi-Fi connection", "err"); };
  xhr.send(fd);
}

/* ------------------------------------------------------------------ sheets */
function sheet(...content) {
  const host = document.getElementById("sheet-host");
  const close = () => host.replaceChildren();
  const bg = h("div", { class: "sheet-bg", onclick: (e) => { if (e.target === bg) close(); } },
    h("div", { class: "sheet", role: "dialog" }, h("div", { class: "grab" }), ...content(close)));
  host.replaceChildren(bg);
}
function opt(ic, label, fn, cls) { return h("button", { class: "opt " + (cls || ""), onclick: fn }, icon(ic), label); }
function msgSheet(m) {
  sheet((close) => [
    h("div", { class: "reacts" }, REACTIONS.map((r) => h("button", { "aria-label": r, onclick: () => { close(); run(post(`/api/message/${m.id}/react`, { r })).then(loadMsgs); } }, icon(r)))),
    opt("reply", "Reply", () => { close(); S.replyTo = m; render(); document.getElementById("composer")?.focus(); }),
    opt("copy", "Copy text", () => { close(); navigator.clipboard?.writeText(m.body).then(() => toast("Copied", "ok")); }),
    opt("trash-2", "Delete for me", () => { close(); run(post(`/api/message/${m.id}/delete`)).then(loadMsgs); }),
    m.dir === "out" ? opt("trash-2", "Delete for everyone", () => { close(); run(post(`/api/message/${m.id}/delete?everyone=true`)).then(loadMsgs); }, "bad") : null,
  ]);
}
async function contactSheet(c) {
  let full = c;
  try { full = await api(`/api/contacts/${c.id}`); } catch (_) { /* */ }
  sheet((close) => [
    h("div", { style: "padding:4px 10px 10px" }, h("div", { class: "faint" }, "SAFETY NUMBER - compare with the other device"),
      h("div", { class: "mono", style: "font-size:20px;color:var(--cyan);letter-spacing:2px" }, full.safety || "--"),
      h("div", { class: "faint" }, full.uid)),
    opt("badge-check", full.verified ? "Remove verification" : "Numbers match - mark verified", () => { close(); run(post(`/api/contacts/${c.id}/verify`)).then(loadContact); }),
    opt("star", full.favorite ? "Remove from favorites" : "Add to favorites", () => { close(); run(post(`/api/contacts/${c.id}/favorite`)); }),
    full.online ? opt("unlink", "Disconnect", () => { close(); run(post(`/api/contacts/${c.id}/disconnect`)); })
      : opt("link", "Reconnect", () => { close(); run(post(`/api/contacts/${c.id}/connect`), "Connected"); }),
    opt("ban", "Block", () => { close(); if (confirm(`Block ${c.name}?`)) run(post(`/api/contacts/${c.id}/block`), "Blocked").then(closeChat); }, "bad"),
  ]);
}

/* ------------------------------------------------------------------ people */
function peopleView() {
  const segs = [["everyone", "Everyone"], ["accepted", "Connections"], ["requests", "Requests"], ["blocked", "Blocked"]];
  const list = h("div", { class: "scroll cards", id: "people" });
  fillPeople(list);
  return h("section", { class: "panel wide" }, topbar("People"),
    h("div", { style: "display:flex;gap:6px;padding:10px 12px 0;overflow-x:auto" },
      segs.map(([k, l]) => h("button", { class: "btn " + (S.people === k ? "primary" : ""), style: "min-height:36px",
        onclick: () => { S.people = k; render(); loadPeople(); } }, l, k === "requests" && S.me?.requests ? ` (${S.me.requests})` : ""))),
    list);
}
function fillPeople(list) {
  list = list || document.getElementById("people");
  if (!list) return;
  if (S.people === "everyone") { fillEveryone(list); return; }
  if (!S.peopleList.length) {
    list.replaceChildren(h("div", { class: "empty" }, icon("users"), h("div", {},
      { accepted: "No connections yet", requests: "No pending requests", blocked: "Nobody is blocked" }[S.people])));
    return;
  }
  list.replaceChildren(...S.peopleList.map((c) => {
    const acts = [];
    if (c.status === "pending_in") {
      acts.push(h("button", { class: "btn primary", onclick: () => run(post(`/api/contacts/${c.id}/accept`), `Connected with ${c.name}`).then(loadPeople) }, icon("check"), "Accept"),
        h("button", { class: "btn", onclick: () => run(post(`/api/contacts/${c.id}/reject`)).then(loadPeople) }, icon("x"), "Decline"));
    } else if (c.status === "pending_out") acts.push(h("span", { class: "pill blue" }, "Waiting for response"));
    else if (c.status === "accepted") acts.push(h("button", { class: "btn primary", onclick: () => openChat(c.id) }, icon("message-square"), "Message"));
    if (c.status !== "blocked") acts.push(followBtn(c, loadPeople));
    else if (c.status === "blocked") acts.push(h("button", { class: "btn", onclick: () => run(post(`/api/contacts/${c.id}/unblock`)).then(loadPeople) }, icon("user-check"), "Unblock"));
    return h("div", { class: "card" }, h("div", { class: "row", style: "padding:0;cursor:default" }, avatar(c, "", c.status === "accepted" ? c.online : undefined),
      h("div", { class: "grow", onclick: () => profileSheet(c.id), style: "cursor:pointer" }, h("div", { class: "title" }, c.name, tick(c.tick)),
        h("div", { class: "sub" }, c.online ? `Online - ${c.transport}` : "@" + c.username),
        h("div", { class: "faint" }, `${c.followers || 0} followers${c.follows_me ? " · follows you" : ""}`))),
      c.about ? h("div", { class: "faint hide-watch", style: "margin-top:6px" }, c.about) : null,
      h("div", { class: "actions" }, acts));
  }));
}

/* ------------------------------------------------------------------ nearby */
function nearbyView() {
  const scanning = S.nearby ? S.nearby.scanning : true;
  const list = h("div", { class: "scroll cards", id: "nearby" });
  fillNearby(list);
  return h("section", { class: "panel wide" }, topbar("Nearby",
    h("button", { class: "btn " + (scanning ? "" : "primary"), style: "min-height:36px",
      onclick: () => run(post("/api/scan", { on: !scanning })).then(loadNearby) }, icon(scanning ? "bluetooth" : "bluetooth-searching"), scanning ? "Stop" : "Scan")),
    list);
}
function bars(n) { return h("span", { class: "signal", title: n ? `Signal ${n}/4` : "Signal unknown" }, [1, 2, 3, 4].map((i) => h("i", { class: i <= n ? "on" : "", style: `height:${3 + i * 3}px` }))); }
function fillNearby(list) {
  list = list || document.getElementById("nearby");
  if (!list || !S.nearby) return;
  const peers = S.nearby.peers;
  const head = h("div", { class: "section" }, S.nearby.scanning ? `Your PC is scanning - ${peers.length} found` : "Scanning is paused");
  if (!peers.length) {
    list.replaceChildren(head, h("div", { class: "empty" }, icon("radar"), h("div", {}, "No one found yet"),
      h("div", { class: "faint" }, "Blue Cench Chat must be open on the other PC with visibility on. Your PC searches over Bluetooth LE and the local network.")));
    return;
  }
  list.replaceChildren(head, ...peers.map((p) => {
    const tp = p.transports.map((t) => h("span", { class: "pill cyan" }, t === "lan" ? "Wi-Fi / LAN" : "Bluetooth"));
    let action;
    if (p.status === "accepted" && p.online) action = h("button", { class: "btn primary", onclick: () => openChat(p.contact_id) }, icon("message-square"), "Chat");
    else if (p.status === "pending_in") action = h("button", { class: "btn primary", onclick: () => { S.people = "requests"; switchTab("people"); } }, "Review request");
    else if (p.status === "blocked") action = h("span", { class: "pill red" }, "Blocked");
    else action = h("button", { class: "btn primary", disabled: !p.transports.length,
      onclick: (e) => { e.target.disabled = true; run(post("/api/nearby/connect", { key: p.key }), p.status === "accepted" ? "Connected" : "Request sent").then(loadNearby); } },
      icon("user-plus"), p.status === "accepted" ? "Connect" : p.status === "pending_out" ? "Resend" : "Connect");
    return h("div", { class: "card" }, h("div", { class: "row", style: "padding:0;cursor:default" },
      avatar({ name: p.name, uid: p.uid || p.key }, ""),
      h("div", { class: "grow" }, h("div", { class: "title" }, p.name), h("div", { class: "sub" }, p.uid || (p.sources.includes("paired") ? "Paired with Windows" : "Identity checked on connect"))),
      bars(p.bars)),
      h("div", { class: "actions", style: "align-items:center" }, tp.length ? tp : h("span", { class: "pill amber" }, "No route yet"), h("span", { style: "flex:1" }), action));
  }));
}

/* ------------------------------------------------------------------ files */
const TSTATUS = { preparing: ["Preparing", ""], queued: ["Queued", ""], waiting: ["Waiting", "blue"], offered: ["Needs approval", "amber"],
  active: ["Transferring", "cyan"], paused: ["Paused", "amber"], completed: ["Verified", "green"], failed: ["Failed", "red"],
  cancelled: ["Cancelled", ""], rejected: ["Declined", ""], interrupted: ["Interrupted", "amber"] };
function tcard(t, compact) {
  const [label, tone] = TSTATUS[t.status] || [t.status, ""];
  const frac = t.status === "completed" ? 1 : t.total ? t.done / t.total : 0;
  const act = (a) => () => run(post(`/api/transfers/${t.id}/${a}`)).then(() => loadTransfers(true));
  const btns = [];
  if (t.dir === "in" && t.status === "offered") btns.push(h("button", { class: "btn primary", onclick: act("accept") }, icon("download"), "Accept"), h("button", { class: "btn", onclick: act("decline") }, "Decline"));
  if (t.status === "active") btns.push(h("button", { class: "btn", onclick: act("pause") }, icon("pause"), "Pause"));
  if (t.status === "paused") btns.push(h("button", { class: "btn", onclick: act("resume") }, icon("play"), "Resume"));
  if (["interrupted", "failed"].includes(t.status)) btns.push(h("button", { class: "btn", onclick: act("retry") }, icon("rotate-cw"), "Retry"));
  if (["active", "paused", "waiting", "queued", "interrupted"].includes(t.status)) btns.push(h("button", { class: "btn ghost", onclick: act("cancel") }, icon("x"), "Cancel"));
  const downloads = t.files.filter((f) => f.downloadable).slice(0, compact ? 3 : 50).map((f) =>
    h("a", { class: "btn", href: `/api/files/${t.id}/${f.i}`, download: f.path.split("/").pop() }, icon("download"), compact ? "Save" : f.path));
  const stats = [`${size(t.done)} of ${size(t.total)}`];
  if (t.status === "active") stats.push(`${size(t.speed)}/s`, `${dur(t.eta)} left`);
  if (t.error && !["completed", "active"].includes(t.status)) stats.push(t.error);
  return h("div", { class: "card" },
    h("div", { class: "row", style: "padding:0;cursor:default" }, h("span", { class: t.dir === "in" ? "cyan" : "" }, icon(fileIcon(t.label), "lg")),
      h("div", { class: "grow" }, h("div", { class: "title" }, t.label),
        h("div", { class: "sub" }, `${t.dir === "in" ? "From" : "To"} ${t.contact}${t.transport ? " - " + t.transport : ""}`)),
      h("span", { class: "pill " + tone }, label)),
    h("div", { class: "bar " + ({ completed: "done", failed: "err", paused: "paused", interrupted: "paused" }[t.status] || "") }, h("i", { style: `width:${(frac * 100).toFixed(1)}%` })),
    h("div", { class: "faint" }, stats.join("  |  ")),
    btns.length || downloads.length ? h("div", { class: "actions" }, btns, downloads) : null);
}
function filesView() {
  const list = h("div", { class: "scroll cards", id: "files" });
  fillFiles(list);
  return h("section", { class: "panel wide" }, topbar("Files"), list);
}
function fillFiles(list) {
  list = list || document.getElementById("files");
  if (!list) return;
  const live = S.transfers.filter((t) => ["offered", "active", "paused", "waiting", "queued", "preparing", "interrupted"].includes(t.status));
  const done = S.transfers.filter((t) => !live.includes(t));
  const kids = [];
  if (live.length) kids.push(h("div", { class: "section" }, "In progress"), ...live.map((t) => tcard(t)));
  if (done.length) kids.push(h("div", { class: "section" }, "History"), ...done.slice(0, 40).map((t) => tcard(t)));
  if (!kids.length) kids.push(h("div", { class: "empty" }, icon("arrow-left-right"), h("div", {}, "No transfers yet"),
    h("div", { class: "faint" }, "Open a chat and tap the paperclip to send photos, videos or documents from this device.")));
  list.replaceChildren(...kids);
}

/* ------------------------------------------------------------------ more */
function moreView() {
  const m = S.me || {};
  const vis = h("button", { class: "toggle" + (m.visible ? " on" : ""), "aria-label": "Visible to nearby users",
    onclick: () => run(post("/api/visible", { on: !m.visible })).then(loadMe) });
  const status = (ok, text) => h("div", { class: "kv" }, h("span", {}, text), h("span", { class: ok ? "ok" : "faint" }, icon(ok ? "circle-check" : "circle-alert", "sm")));
  const notifs = S.notifs.slice(0, 30).map((n) => h("div", { class: "row", style: "cursor:default" },
    h("span", { class: n.read ? "faint" : "cyan" }, icon({ request: "user-plus", accepted: "user-check", file_offer: "download", transfer_done: "circle-check", transfer_failed: "circle-alert", security: "shield-alert", disconnect: "unlink" }[n.kind] || "bell")),
    h("div", { class: "grow" }, h("div", { class: "title" }, n.title), n.body ? h("div", { class: "sub" }, n.body) : null),
    h("span", { class: "faint" }, ago(n.ts))));
  return h("section", { class: "panel wide" }, topbar("Profile"), h("div", { class: "scroll cards" },
    profileHeader() || h("div", { class: "card" }, h("h3", {}, m.name || ""), h("div", { class: "mono faint" }, m.uid || "")),
    h("div", { class: "card" }, h("h3", {}, "Your PC"),
      status(m.bluetooth === "on", `Bluetooth ${m.bluetooth || ""}`), status(m.ble_advertising, "Discoverable over Bluetooth LE"),
      status(m.rfcomm, "Bluetooth RFCOMM link"), status(m.lan, `Local network ${(m.ips || []).join(", ")}`),
      h("div", { class: "kv" }, h("span", {}, "Visible to nearby users"), vis)),
    h("div", { class: "card" }, h("h3", {}, "Alerts"), notifs.length ? notifs : h("div", { class: "faint" }, "You're all caught up.")),
    h("div", { class: "card" }, h("h3", {}, "This device"), h("div", { class: "faint" }, `Paired as "${m.device || ""}". It uses your PC's Blue Cench Chat account over Wi-Fi.`),
      h("div", { class: "actions" }, h("button", { class: "btn danger", onclick: () => { if (confirm("Unpair this device?")) run(post("/api/logout")).then(() => showPair()); } }, icon("log-out"), "Unpair this device")))));
}

/* ------------------------------------------------------------------ home (Instagram-style) */
function followBtn(c, after) {
  const on = !!c.i_follow;
  return h("button", { class: "btn " + (on ? "following" : "follow"),
    onclick: (e) => { e.stopPropagation(); run(post(`/api/follow/${c.id}`, { on: !on })).then(() => { (after || loadHome)(); }); } },
    on ? "Following" : (c.follows_me ? "Follow back" : "Follow"));
}
function ringAv(c, cls, on) { return h("span", { class: "ring" + (on ? "" : " off") }, avatar(c, cls)); }
function notesBar() {
  const n = S.notes || { me: { name: "", text: "", music: "" }, people: [] };
  const cell = (c, text, music, label, onclick) => h("button", { class: "note", onclick },
    h("div", { class: "bub" + (text || music ? "" : " empty") }, text || (music ? "♫ " + music : "Note..."), text && music ? h("div", {}, "♫ " + music) : null),
    ringAv(c, "", !!(text || music)), h("div", { class: "nm" }, label));
  return h("div", { class: "notes" },
    cell({ name: n.me.name, uid: S.me?.uid, has_avatar: false }, n.me.text, n.me.music, "Your note", noteSheet),
    n.people.map((p) => cell(p, p.note, p.music, p.name.split(" ")[0], () => profileSheet(p.id))));
}
function postCard(p) {
  const who = { id: p.author_id, name: p.author, uid: p.uid, has_avatar: false };
  const like = () => run(post(`/api/posts/${p.id}/like`)).then(loadHome);
  const img = p.has_image ? h("img", { class: "img", src: `/api/posts/${p.id}/image`, alt: p.caption || "Photo", loading: "lazy",
    ondblclick: () => { if (!p.liked) like(); } }) : h("div", { class: "text-only" }, p.caption);
  return h("article", { class: "post" },
    h("div", { class: "ph" }, avatar(who, "sm"),
      h("div", { class: "grow", onclick: () => p.author_id && profileSheet(p.author_id), style: "cursor:pointer" },
        h("b", {}, p.author), tick(p.tick), h("span", { class: "faint" }, " · " + ago(p.ts)),
        p.music ? h("div", { class: "faint" }, "♫ " + p.music) : null),
      p.mine ? h("button", { class: "icon-btn", "aria-label": "Post options", onclick: () => sheet((close) => [
        opt("trash-2", "Delete post", () => { close(); if (confirm("Delete this post?")) run(post(`/api/posts/${p.id}/delete`), "Deleted").then(loadHome); }, "bad")]) }, icon("ellipsis")) : null),
    img,
    h("div", { class: "acts" },
      h("button", { class: "icon-btn" + (p.liked ? " liked" : ""), "aria-label": p.liked ? "Unlike" : "Like", onclick: like }, icon("heart")),
      h("button", { class: "icon-btn", "aria-label": "Comments", onclick: () => commentsSheet(p) }, icon("message-circle")),
      h("span", { class: "grow" }),
      h("button", { class: "icon-btn" + (p.saved ? " saved" : ""), "aria-label": p.saved ? "Unsave" : "Save",
        onclick: () => run(post(`/api/posts/${p.id}/save`)).then(loadHome) }, icon("bookmark"))),
    h("div", { class: "body" },
      p.likes ? h("div", { class: "lk" }, `${p.likes} like${p.likes === 1 ? "" : "s"}`) : null,
      p.has_image && p.caption ? h("div", {}, h("b", {}, p.author), " ", p.caption) : null,
      p.comments ? h("button", { class: "more", onclick: () => commentsSheet(p) }, `View all ${p.comments} comment${p.comments === 1 ? "" : "s"}`) : null));
}
function homeView() {
  const feed = S.feed.length ? S.feed.map(postCard) : [h("div", { class: "empty" }, icon("house"),
    h("div", {}, "Your feed is empty"), h("div", { class: "faint" }, "Follow people in the People tab to see their posts, or share your first post."))];
  return h("section", { class: "panel wide" }, topbar("Blue Cench Chat",
    h("button", { class: "icon-btn", "aria-label": "Switch light or dark", onclick: toggleTheme }, icon({ light: "moon", dark: "sparkles", midnight: "sun" }[getTheme()] || "moon")),
    h("button", { class: "icon-btn", "aria-label": "New post", onclick: composeSheet }, icon("square-plus"))),
    h("div", { class: "scroll" }, notesBar(), h("div", { class: "feed" }, feed)));
}
function noteSheet() {
  const me = (S.notes && S.notes.me) || { text: "", music: "" };
  const t = h("input", { class: "field", maxlength: "60", placeholder: "Share a thought... (60 characters)", value: me.text });
  const m = h("input", { class: "field", maxlength: "80", placeholder: "♫ Song - artist (optional)", value: me.music });
  sheet((close) => [h("h3", {}, "Your note"), h("div", { class: "faint" }, "Your followers and people nearby see it above your photo."), t, m,
    h("div", { class: "actions" },
      h("button", { class: "btn", onclick: () => { close(); run(post("/api/note", { text: "", music: "" })).then(loadHome); } }, "Delete"),
      h("button", { class: "btn primary", onclick: () => { close(); run(post("/api/note", { text: t.value, music: m.value }), "Note shared").then(loadHome); } }, "Share"))]);
  setTimeout(() => t.focus(), 50);
}
function composeSheet() {
  let file = null;
  const preview = h("img", { class: "compose-img hidden", alt: "" });
  const pick = h("input", { type: "file", accept: "image/*", class: "hidden", onchange: (e) => {
    file = e.target.files[0] || null;
    if (file) { preview.src = URL.createObjectURL(file); preview.classList.remove("hidden"); }
  } });
  const cap = h("textarea", { class: "field", rows: "3", maxlength: "2200", placeholder: "Write a caption..." });
  const mus = h("input", { class: "field", maxlength: "80", placeholder: "♫ Add music: song - artist (optional)" });
  sheet((close) => [h("h3", {}, "New post"), preview, pick,
    h("button", { class: "btn block", onclick: () => pick.click() }, icon("image-plus"), "Choose photo"), cap, mus,
    h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => {
      if (!file && !cap.value.trim()) { toast("Add a photo or write a caption", "warn"); return; }
      const fd = new FormData(); fd.append("caption", cap.value); fd.append("music", mus.value);
      if (file) fd.append("image", file);
      close(); toast("Sharing...");
      run(postForm("/api/posts", fd), "Shared").then(loadHome);
    } }, icon("send"), "Share"))]);
}
async function commentsSheet(p) {
  let list = [];
  try { list = await api(`/api/posts/${p.id}/comments`); } catch (_) { /* */ }
  const box = h("input", { class: "field", maxlength: "500", placeholder: "Add a comment..." });
  const submit = (close) => { const t = box.value.trim(); if (!t) return; close(); run(post(`/api/posts/${p.id}/comments`, { text: t })).then(() => { loadHome(); commentsSheet(p); }); };
  sheet((close) => [h("h3", {}, "Comments"),
    list.length ? list.map((c) => h("div", { class: "comment" }, avatar({ name: c.name, uid: c.uid }, "sm"),
      h("div", {}, h("b", {}, c.name), " ", c.text, h("div", { class: "faint" }, ago(c.ts))))) : h("div", { class: "faint" }, "No comments yet."),
    box, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => submit(close) }, "Post"))]);
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(() => document.getElementById("sheet-host").replaceChildren()); });
}
function grid(posts) {
  return h("div", { class: "grid3" }, posts.map((p) => {
    const t = h("button", { class: "tile", "aria-label": p.caption || "Post", onclick: () => sheet(() => [postCard(p)]) }, p.has_image ? "" : p.caption.slice(0, 80));
    if (p.has_image) t.style.backgroundImage = `url(/api/posts/${p.id}/image)`;
    return t;
  }));
}
async function profileSheet(cid) {
  let c;
  try { c = await api(`/api/profile/${cid}`); } catch (e) { toast(e.message, "err"); return; }
  sheet((close) => [h("div", { class: "prof" },
    h("div", { class: "head" }, ringAv(c, "lg", !!(c.note || c.music)),
      h("div", { class: "counts" }, h("div", {}, h("b", {}, c.posts || 0), h("span", {}, "posts")),
        h("div", {}, h("b", {}, c.followers || 0), h("span", {}, "followers")), h("div", {}, h("b", {}, c.following || 0), h("span", {}, "following")))),
    h("h3", {}, c.name, tick(c.tick)), h("div", { class: "faint" }, "@" + c.username + (c.follows_me ? " · follows you" : "")),
    c.about ? h("div", {}, c.about) : null,
    c.note || c.music ? h("div", { class: "muted" }, "Note: " + (c.note || "") + (c.music ? "  ♫ " + c.music : "")) : null,
    h("div", { class: "actions" }, c.status !== "blocked" ? followBtn(c, () => { close(); profileSheet(cid); loadHome(); }) : null,
      c.status === "accepted" ? h("button", { class: "btn", onclick: () => { close(); openChat(c.id); } }, icon("message-square"), "Message") : null)),
    c.posts_list.length ? grid(c.posts_list) : h("div", { class: "faint", style: "padding:0 16px 16px" }, c.i_follow ? "No posts yet." : "Follow to see their posts.")]);
}
function profileHeader() {
  const p = S.profile;
  if (!p) return null;
  const canAsk = p.followers >= p.need;
  return h("div", { class: "card prof" },
    h("div", { class: "head" }, ringAv({ name: p.name, uid: p.uid }, "lg", !!(p.note.text || p.note.music)),
      h("div", { class: "counts" }, h("div", {}, h("b", {}, p.posts), h("span", {}, "posts")),
        h("div", {}, h("b", {}, p.followers), h("span", {}, "followers")), h("div", {}, h("b", {}, p.following), h("span", {}, "following")))),
    h("h3", {}, p.username, tick(p.tick)), h("div", {}, p.name), p.about ? h("div", { class: "muted" }, p.about) : null,
    p.note.text || p.note.music ? h("div", { class: "faint" }, "Note: " + p.note.text + (p.note.music ? "  ♫ " + p.note.music : "")) : null,
    h("div", { class: "actions" },
      h("button", { class: "btn", onclick: noteSheet }, icon("music"), "Edit note"),
      h("button", { class: "btn", onclick: composeSheet }, icon("square-plus"), "New post"),
      h("button", { class: "btn", onclick: toggleTheme }, icon({ light: "moon", dark: "sparkles", midnight: "sun" }[getTheme()] || "moon"), ({ light: "Dark mode", dark: "Midnight Blue", midnight: "Light mode" }[getTheme()] || "Dark mode"))),
    p.tick ? null : p.tick_requested ? h("div", { class: "faint" }, "Blue tick requested - waiting for review.")
      : h("div", { class: "actions" }, h("button", { class: "btn " + (canAsk ? "follow" : ""), disabled: !canAsk,
        onclick: () => run(post("/api/tick/request", { message: "" })).then((r) => { if (r) toast(r.message, "ok"); loadProfile(); }) },
        icon("badge-check"), "Request blue tick"), canAsk ? null : h("span", { class: "faint" }, `${p.followers}/${p.need} followers needed`)),
    p.admin ? h("div", { class: "faint" }, "Give and remove blue ticks from the Verification page in the PC app.") : null,
    p.posts_list.length ? grid(p.posts_list) : null);
}

/* ------------------------------------------------------------------ data loading */
async function loadMe() {
  try { S.me = await api("/api/me"); } catch (_) { return; }
  document.querySelectorAll(".nav button").forEach((b, i) => {
    const n = badgeFor(TABS[i][0]);
    let el = b.querySelector(".badge");
    if (n && !el) { el = h("span", { class: "badge" }); b.append(el); }
    if (el) { if (n) el.textContent = n > 99 ? "99+" : n; else el.remove(); }
  });
  if (S.tab === "more") render();
}
async function loadHome() {
  try { [S.feed, S.notes] = await Promise.all([api("/api/feed"), api("/api/notes")]); } catch (_) { return; }
  if (S.tab === "home") render();
}
async function loadProfile() {
  try { S.profile = await api("/api/profile"); } catch (_) { return; }
  if (S.tab === "more") render();
}
async function loadConvs() {
  try { S.convs = await api("/api/conversations"); } catch (_) { return; }
  fillConvs();
}
async function loadMsgs() {
  if (!S.chat) return;
  const id = S.chat;
  try { const msgs = await api(`/api/messages/${id}`); if (S.chat === id) { S.msgs = msgs; fillMsgs(); } } catch (_) { /* */ }
}
async function loadContact() {
  if (!S.chat) return;
  try { S.contact = await api(`/api/contacts/${S.chat}`); } catch (_) { return; }
  const st = document.getElementById("chat-status");
  if (st && !S.typing[S.chat]) st.textContent = S.contact.online ? `Online - ${S.contact.transport}` : `Offline - last seen ${ago(S.contact.last_seen)}`;
}
async function loadPeople() {
  if (S.people === "everyone") {
    try { S.everyone = await api("/api/everyone"); } catch (_) { return; }
    fillPeople();
    return;
  }
  try { S.peopleList = await api(`/api/contacts?group=${S.people}`); } catch (_) { return; }
  fillPeople();
}
async function openPerson(p, then) {
  const r = await run(post(`/api/everyone/${encodeURIComponent(p.fuid)}/open`));
  if (r && r.id) then(r.id);
}
function fillEveryone(list) {
  const e = S.everyone || { online: false, people: [] };
  if (!e.online) {
    list.replaceChildren(h("div", { class: "empty" }, icon("wifi-off"), h("div", {}, "Online mode is off"),
      h("div", { class: "faint" }, "Turn it on in the PC app (Everyone page) to find and text people anywhere.")));
    return;
  }
  if (!e.people.length) { list.replaceChildren(h("div", { class: "empty" }, icon("users"), h("div", {}, "Nobody else online yet"))); return; }
  list.replaceChildren(...e.people.map((p) => h("div", { class: "card" },
    h("div", { class: "row", style: "padding:0;cursor:default" }, avatar({ name: p.name, uid: p.uid }, "", p.online),
      h("div", { class: "grow" }, h("div", { class: "title" }, p.name || p.username, tick(p.tick)),
        h("div", { class: "sub" }, "@" + p.username + (p.follows_me ? " · follows you" : "")),
        h("div", { class: "faint" }, `${p.followers} followers · ${p.posts} posts`))),
    p.note ? h("div", { class: "faint", style: "margin-top:6px" }, "Note: " + p.note) : null,
    h("div", { class: "actions" },
      h("button", { class: "btn " + (p.i_follow ? "following" : "follow"), disabled: p.blocked,
        onclick: () => openPerson(p, (id) => run(post(`/api/follow/${id}`, { on: !p.i_follow })).then(loadPeople)) },
        p.i_follow ? "Following" : (p.follows_me ? "Follow back" : "Follow")),
      h("button", { class: "btn", disabled: p.blocked, onclick: () => openPerson(p, (id) => openChat(id)) }, icon("message-square"), "Message")))));
}
async function loadNearby() {
  try { S.nearby = await api("/api/nearby"); } catch (_) { return; }
  if (S.tab === "nearby") { if (!document.getElementById("nearby")) render(); else { render(); } }
}
async function loadTransfers(quiet) {
  try { S.transfers = await api("/api/transfers"); } catch (_) { return; }
  S.tmap = Object.fromEntries(S.transfers.map((t) => [t.id, t]));
  fillFiles();
  if (S.chat) fillMsgs();
  if (!quiet) loadMe();
}
async function loadNotifs() {
  try { S.notifs = await api("/api/notifications"); } catch (_) { return; }
  if (S.tab === "more") { render(); post("/api/notifications/read").then(loadMe).catch(() => {}); }
}

/* ------------------------------------------------------------------ live updates */
const later = {
  convs: debounce(loadConvs, 250), msgs: debounce(loadMsgs, 120), me: debounce(loadMe, 400), people: debounce(loadPeople, 300),
  nearby: debounce(loadNearby, 700), files: debounce(() => loadTransfers(true), 400), notifs: debounce(loadNotifs, 400),
  contact: debounce(loadContact, 300), home: debounce(loadHome, 300), profile: debounce(loadProfile, 400),
};
function connectWs() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/api/ws");
  S.ws = ws;
  const ping = setInterval(() => { if (ws.readyState === 1) ws.send("ping"); }, 20000);
  ws.onmessage = (ev) => {
    let d; try { d = JSON.parse(ev.data); } catch (_) { return; }
    const [a0, a1] = d.a || [];
    switch (d.e) {
      case "messages": case "message":
        later.convs(); later.me(); if (a0 === S.chat) { later.msgs(); if (document.visibilityState === "visible") later.read(); }
        if (d.e === "message" && a0 !== S.chat) { const c = S.convs.find((x) => x.id === a0); if (c) toast(`New message from ${c.name}`); }
        break;
      case "contacts": case "session": later.convs(); later.me(); later.contact(); if (S.tab === "people") later.people(); if (S.tab === "nearby") later.nearby(); break;
      case "peers": if (S.tab === "nearby") later.nearby(); break;
      case "transfer": later.files(); break;
      case "transfer_offer": toast("Incoming files - open the Files tab to accept", "warn"); later.files(); later.me(); break;
      case "notification": later.me(); if (S.tab === "more") later.notifs(); break;
      case "request": toast("New connection request - see People", "warn"); later.me(); break;
      case "typing":
        S.typing[a0] = !!a1;
        if (a0 === S.chat) {
          const el = document.getElementById("typing"); const st = document.getElementById("chat-status");
          if (el) el.replaceChildren(...(a1 ? [signal((S.contact && S.contact.name) || "")] : []));
          if (st && a1) st.textContent = "typing...";
          if (a1) setTimeout(() => { S.typing[a0] = false; if (el) el.textContent = ""; later.contact(); }, 5000);
        }
        break;
      case "status": later.me(); break;
      case "cloud": if (S.tab === "people") later.people(); break;
      case "social": if (S.tab === "home") later.home(); if (S.tab === "more") later.profile(); if (S.tab === "people") later.people(); break;
      default: break;
    }
  };
  ws.onclose = (ev) => {
    clearInterval(ping);
    if (S.ws !== ws) return;
    if (ev.code === 4401) { showPair(); return; }
    setTimeout(() => { if (S.ws === ws) connectWs(); }, 2500);
  };
}
later.read = debounce(() => { if (S.chat) post(`/api/messages/${S.chat}/read`).catch(() => {}); }, 500);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && S.me) { loadMe(); loadConvs(); if (S.chat) { loadMsgs(); later.read(); } } });
wide.addEventListener("change", () => { if (S.me) render(); });
setInterval(() => { if (S.transfers.some((t) => t.status === "active") && (S.tab === "files" || S.chat)) loadTransfers(true); }, 1500);

/* ------------------------------------------------------------------ start */
async function start() {
  let s;
  try { s = await (await fetch("/api/session", { credentials: "same-origin" })).json(); } catch (_) {
    root.replaceChildren(h("div", { class: "pair" }, h("div", { class: "pair-card" }, h("h1", {}, "Can't reach your PC"),
      h("div", { class: "muted" }, "Make sure Blue Cench Chat is running on the PC and this device is on the same Wi-Fi."),
      h("div", { style: "height:12px" }), h("button", { class: "btn primary block", onclick: start }, icon("rotate-cw"), "Try again"))));
    return;
  }
  if (!s.paired) { showPair(); return; }
  await loadMe();
  S.tab = "home";
  await Promise.all([loadConvs(), loadTransfers(true), loadHome()]);
  render();
  connectWs();
}
start();
