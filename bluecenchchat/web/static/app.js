/* Blue Cench Chat web app - phones, tablets, watches. Talks only to the Blue Cench Chat PC on the same network. */
"use strict";

const S = {
  me: null, tab: "chats", chat: null, convs: [], msgs: [], replyTo: null, typing: {}, nearby: null,
  transfers: [], tmap: {}, people: "accepted", peopleList: [], notifs: [], q: "", ws: null, contact: null,
};
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
const TABS = [["chats", "Chats", "message-square"], ["people", "People", "users"], ["nearby", "Nearby", "radar"],
  ["files", "Files", "arrow-left-right"], ["more", "More", "settings"]];

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
  } else if (S.tab === "people") main.append(peopleView());
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
  ({ chats: loadConvs, people: loadPeople, nearby: loadNearby, files: loadTransfers, more: loadNotifs })[tab]();
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
      h("div", { class: "grow" }, h("div", { class: "title" }, c.name, c.verified ? h("span", { class: "ok" }, icon("badge-check", "sm")) : null),
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
    h("span", {}, "Replying: " + S.replyTo.body), h("button", { class: "icon-btn", onclick: () => { S.replyTo = null; render(); }, "aria-label": "Cancel reply" }, icon("x", "sm"))) : null;
  return h("section", { class: wide.matches ? "detail" : "panel" }, h("div", { class: "chat" },
    h("div", { class: "top" },
      h("button", { class: "icon-btn back", onclick: () => history.length > 1 && !wide.matches ? history.back() : closeChat(), "aria-label": "Back" }, icon("chevron-left")),
      avatar(c, "sm", c.online),
      h("div", { class: "who" }, h("b", {}, c.name, c.verified ? h("span", { class: "ok" }, icon("badge-check", "sm")) : null),
        h("span", { id: "chat-status" }, status)),
      h("button", { class: "icon-btn", onclick: () => contactSheet(c), "aria-label": "Contact options" }, icon("ellipsis-vertical"))),
    h("div", { class: "msgs", id: "msgs" }, msgNodes()),
    h("div", { class: "typing", id: "typing" }, S.typing[S.chat] ? `${c.name} is typing...` : ""),
    c.status === "accepted" ? h("div", { class: "quick" }, QUICK.map((q) => h("button", { onclick: () => sendText(q) }, q))) : null,
    reply,
    h("div", { class: "composer" },
      h("button", { class: "icon-btn attach", onclick: () => file.click(), "aria-label": "Send files", disabled: c.status !== "accepted" }, icon("paperclip")),
      file, box,
      h("button", { class: "send", onclick: () => send(box), "aria-label": "Send" }, icon("send")))));
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
    const quoted = m.reply_to ? S.msgs.find((x) => x.id === m.reply_to) : null;
    const st = { queued: "clock", sent: "check", delivered: "check-check", read: "check-check", failed: "circle-alert" }[m.status];
    out.push(h("div", { class: `b ${m.dir}${m.reaction ? " has-rx" : ""}`, onclick: () => msgSheet(m) },
      m.reply_to ? h("div", { class: "q" }, quoted ? quoted.body.slice(0, 120) : "Earlier message") : null,
      m.body,
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
  const segs = [["accepted", "Connections"], ["requests", "Requests"], ["blocked", "Blocked"]];
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
    else if (c.status === "blocked") acts.push(h("button", { class: "btn", onclick: () => run(post(`/api/contacts/${c.id}/unblock`)).then(loadPeople) }, icon("user-check"), "Unblock"));
    return h("div", { class: "card" }, h("div", { class: "row", style: "padding:0;cursor:default" }, avatar(c, "", c.status === "accepted" ? c.online : undefined),
      h("div", { class: "grow" }, h("div", { class: "title" }, c.name, c.verified ? h("span", { class: "ok" }, icon("badge-check", "sm")) : null),
        h("div", { class: "sub" }, c.online ? `Online - ${c.transport}` : "@" + c.username))),
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
  return h("section", { class: "panel wide" }, topbar("More"), h("div", { class: "scroll cards" },
    h("div", { class: "card" }, h("div", { class: "row", style: "padding:0;cursor:default" },
      avatar({ name: m.name || "", uid: m.uid || "" }, "lg"),
      h("div", { class: "grow" }, h("h3", {}, m.name || ""), h("div", { class: "faint" }, "@" + (m.username || "")), h("div", { class: "mono faint" }, m.uid || ""))),
      m.about ? h("div", { class: "muted", style: "margin-top:8px" }, m.about) : null),
    h("div", { class: "card" }, h("h3", {}, "Your PC"),
      status(m.bluetooth === "on", `Bluetooth ${m.bluetooth || ""}`), status(m.ble_advertising, "Discoverable over Bluetooth LE"),
      status(m.rfcomm, "Bluetooth RFCOMM link"), status(m.lan, `Local network ${(m.ips || []).join(", ")}`),
      h("div", { class: "kv" }, h("span", {}, "Visible to nearby users"), vis)),
    h("div", { class: "card" }, h("h3", {}, "Alerts"), notifs.length ? notifs : h("div", { class: "faint" }, "You're all caught up.")),
    h("div", { class: "card" }, h("h3", {}, "This device"), h("div", { class: "faint" }, `Paired as "${m.device || ""}". It uses your PC's Blue Cench Chat account over Wi-Fi.`),
      h("div", { class: "actions" }, h("button", { class: "btn danger", onclick: () => { if (confirm("Unpair this device?")) run(post("/api/logout")).then(() => showPair()); } }, icon("log-out"), "Unpair this device")))));
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
  try { S.peopleList = await api(`/api/contacts?group=${S.people}`); } catch (_) { return; }
  fillPeople();
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
  contact: debounce(loadContact, 300),
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
          if (el) el.textContent = a1 ? `${(S.contact && S.contact.name) || ""} is typing...` : "";
          if (st && a1) st.textContent = "typing...";
          if (a1) setTimeout(() => { S.typing[a0] = false; if (el) el.textContent = ""; later.contact(); }, 5000);
        }
        break;
      case "status": later.me(); break;
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
  await Promise.all([loadConvs(), loadTransfers(true)]);
  render();
  connectWs();
}
start();
