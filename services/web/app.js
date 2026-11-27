// BMW Configurator Assistant - web client.
// Renders the agent's messages and adaptive UI components; every user interaction is sent
// back to the agent service as either a free-text message or a structured action.

import { VoiceMode, voiceSupported } from "./voice.js";
import { applyStatic, eur, lang, mountSwitch, num, setLang, t, words } from "./i18n.js";

const API = "/api";
const $ = (sel) => document.querySelector(sel);
const els = {
  messages: $("#messages"), scroll: $("#scroll"), form: $("#composer"), input: $("#input"), send: $("#send"),
  needs: $("#needs"), assumptions: $("#assumptions"),
  assumptionsBox: $("#assumptions-box"), newSession: $("#new-session"),
  stage: $("#stage"), chatMin: $("#chat-min"), fab: $("#chat-fab"), needsBar: $("#needs-bar"),
  voice: $("#voice"), voiceStatus: $("#voice-status"), voiceLabel: $("#voice-label"), voiceStop: $("#voice-stop"),
};

let sessionId = null;
let busy = false;

// ------------------------------------------------------------------ utils

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
const POWERTRAIN = () => words("powertrain");
const BODY = () => words("body");

// Line-drawn side profiles per body style (no photos in the fictional catalog).
const CAR_PATHS = {
  sav: "M10 46 L10 36 Q12 31 22 30 L38 29 L52 17 Q57 13 65 13 L118 13 Q126 13 131 17 L146 29 Q156 30 158 35 L158 46",
  touring: "M8 46 L8 38 Q10 33 20 32 L40 31 L56 21 Q61 18 68 18 L140 18 Q147 18 150 22 L156 32 L158 46",
  gran_coupe: "M8 46 L8 38 Q10 33 20 32 L42 30 L60 20 Q65 17 72 17 L106 17 Q116 18 126 25 L150 32 Q158 34 158 46",
  tourer: "M10 46 L10 35 Q12 30 22 29 L34 28 L48 15 Q53 11 60 11 L124 11 Q131 11 135 16 L146 30 L150 46",
  sedan: "M8 46 L8 38 Q10 33 20 32 L42 30 L58 20 Q63 17 70 17 L110 17 Q118 17 124 22 L134 30 L154 32 Q158 34 158 46",
};
const WINDOWS = {
  sav: "M56 28 L66 18 L116 18 L128 28 Z", touring: "M60 30 L70 22 L140 22 L146 30 Z",
  gran_coupe: "M62 29 L74 21 L104 21 L120 29 Z", tourer: "M52 27 L62 16 L122 16 L132 27 Z",
  sedan: "M62 29 L72 21 L108 21 L118 29 Z",
};
// Photos per model id (assets/cars/<model_id>.<ext>), filled from the asset manifest.
const CAR_PHOTOS = new Map();
function carVisual(modelId, body, name = "") {
  const photo = CAR_PHOTOS.get(modelId);
  return photo ? `<img class="car-photo" src="${photo}" alt="${esc(name)}" loading="lazy">` : carIcon(body);
}

function carIcon(body) {
  const b = CAR_PATHS[body] ? body : "sedan";
  // Sill line runs from the outline's first to its last point (outlines may end in a line or a curve).
  const xs = CAR_PATHS[b].match(/\d+(?=\s+46\b)/g) || ["10", "158"];
  const [start, end] = [xs[0], xs[xs.length - 1]];
  return `<svg viewBox="0 0 166 60" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" aria-hidden="true">
    <path d="${CAR_PATHS[b]}"/><path d="${WINDOWS[b]}" stroke-width="1.1"/>
    <path d="M${start} 46 L31 46 M53 46 L117 46 M139 46 L${end} 46" />
    <circle cx="42" cy="46" r="11" fill="#fff"/><circle cx="42" cy="46" r="5"/>
    <circle cx="128" cy="46" r="11" fill="#fff"/><circle cx="128" cy="46" r="5"/></svg>`;
}

function h(tag, attrs = {}, html = "") {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  if (html) el.innerHTML = html;
  return el;
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "content-type": "application/json" }, ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.startsWith("/auth/")) {
    location.replace("/login.html");  // session expired or signed out elsewhere
    throw new Error(t("sign_in_please"));
  }
  if (!res.ok) {
    const err = new Error(typeof body.detail === "string" ? body.detail : t("request_failed", { status: res.status }));
    err.status = res.status;
    throw err;
  }
  return body;
}

// ------------------------------------------------------------------ session

async function startSession() {
  const body = await api("/sessions", { method: "POST", body: JSON.stringify({ language: lang() }) });
  sessionId = body.session_id;
  setVoiceAvailable(body.voice);
  voice.interrupt();
  try { localStorage.setItem("sessionId", sessionId); } catch { /* storage unavailable */ }
  els.messages.innerHTML = "";
  document.body.classList.remove("started");
  renderMessage(body.message);
  renderState(body.state);
}

async function restoreSession() {
  let saved = null;
  try { saved = localStorage.getItem("sessionId"); } catch { /* storage unavailable */ }
  if (!saved) return startSession();
  try {
    const body = await api(`/sessions/${saved}`);
    sessionId = saved;
    setVoiceAvailable(body.voice);
    // The language may have been switched in another tab since this conversation started.
    if (body.state.language !== lang()) return switchLanguage(lang());
    renderSession(body);
  } catch {
    await startSession();
  }
}

function renderSession(body) {
  els.messages.innerHTML = "";
  body.transcript.forEach((m) => renderMessage(m));
  if (body.transcript.some((m) => m.role === "user")) document.body.classList.add("started");
  renderState(body.state);
}

// The agent switches the conversation's language (replies, catalog texts, voice); the transcript
// and configuration are then re-read, so names and rule messages appear in the new language too.
async function switchLanguage(code) {
  if (!sessionId) return;
  await whenIdle();
  voice.interrupt();
  await send({ action: { type: "set_language", language: code } }, null, { silent: true, render: false });
  renderSession(await api(`/sessions/${sessionId}`));
}

async function send(payload, echo, { silent = false, render = true } = {}) {
  if (busy) return;
  busy = true;
  setBusy(true);
  if (echo && !silent) renderMessage({ role: "user", text: echo, components: [] }, { animate: true });
  const typing = silent ? null : showTyping();
  try {
    const body = await api(`/sessions/${sessionId}/turn`, { method: "POST", body: JSON.stringify(payload) });
    typing?.remove();
    if (!render) return;
    if (body.message) renderMessage(body.message, { animate: true });
    if (body.message?.text) voice.speak(body.message.text);  // only while voice mode is on
    renderState(body.state);
    if (body.feedback) showFeedback(body.feedback);
    // A conflict caused via the chat is resolved in the same dialog as one caused on the stage.
    const chatConflict = body.message?.components.find((c) => c.type === "conflict");
    if (chatConflict && layout === "configure") openConflict(chatConflict);
    if (chatMinimized && body.message) {
      // Replies that need a decision should not go unnoticed behind the minimized assistant.
      const needsAttention = body.message.components.some((c) => ["notice", "question", "summary"].includes(c.type));
      if (needsAttention) setChatMinimized(false); else els.fab.classList.add("has-new");
    }
  } catch (err) {
    typing?.remove();
    if (silent) { toast(err.message, "error"); return; }
    if (err.status === 404) {
      renderError(t("session_expired"));
      await startSession();
    } else {
      renderError(err.message, () => send(payload));
    }
  } finally {
    busy = false;
    setBusy(false);
  }
}

const say = (text) => send({ message: text }, text);
const act = (action, echo) => send({ action }, echo);
// Option changes are applied by the rules engine and shown on the stage, not in the chat.
const changeOption = (op, optionId, force = false) =>
  send({ action: { type: "change_option", op, option_id: optionId, force } }, null, { silent: true });

function setBusy(on) {
  els.send.disabled = on;
  els.input.disabled = on;
  document.body.classList.toggle("busy", on);
  if (!on) els.input.focus();
}

// ------------------------------------------------------------------ chat rendering

function showTyping() {
  const el = h("div", { class: "msg assistant typing" }, "<span></span><span></span><span></span>");
  els.messages.append(el);
  scroll();
  return el;
}

function renderError(text, retry) {
  if (chatMinimized) setChatMinimized(false);
  const el = h("div", { class: "msg assistant error" }, esc(text) + " ");
  if (retry) el.append(h("button", { class: "link", onclick: () => { el.remove(); retry(); } }, t("retry")));
  els.messages.append(el);
  scroll();
}

// Only the latest assistant message keeps its full UI. Older ones are condensed so the
// conversation stays lean: answered/stale prompts disappear, bigger blocks fold into one line.
const TRANSIENT = ["question", "slider", "conflict", "tradeoffs", "notice"];

function condensePrevious() {
  els.messages.querySelectorAll(".msg.assistant:not(.condensed)").forEach((msg) => {
    msg.classList.add("condensed");
    msg.querySelectorAll(":scope > .comp").forEach((comp) => {
      const type = comp.dataset.type;
      if (TRANSIENT.includes(type)) { comp.remove(); return; }
      const fold = h("details", { class: "fold" }, `<summary>${t("show_earlier", { what: words("fold")[type] || t("details") })}${comp.dataset.hint ? `: ${esc(comp.dataset.hint)}` : ""}</summary>`);
      comp.replaceWith(fold);
      fold.append(comp);
    });
  });
}

// Live replies are revealed rather than dropped in: words fade up in reading order, then the
// cards follow one by one. Restored history (page reload) renders instantly.
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function revealWords(bubble) {
  const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) nodes.push(walker.currentNode);
  const words = [];
  for (const node of nodes) {
    const frag = document.createDocumentFragment();
    for (const part of node.nodeValue.split(/(\s+)/)) {
      if (!part) continue;
      if (/^\s+$/.test(part)) { frag.append(part); continue; }
      const w = h("span", { class: "w" });
      w.textContent = part;
      words.push(w);
      frag.append(w);
    }
    node.replaceWith(frag);
  }
  // Short replies read at a natural pace; long ones never take more than ~1.4 s to appear.
  const step = Math.min(32, 1400 / Math.max(words.length, 1));
  words.forEach((w, i) => { w.style.animationDelay = `${Math.round(i * step)}ms`; });
  return words.length * step;
}

function renderMessage(msg, { animate = false } = {}) {
  animate = animate && !reduceMotion.matches;
  if (msg.role === "assistant") condensePrevious();
  const wrap = h("div", { class: `msg ${msg.role}${animate ? " reveal" : ""}` });
  let textMs = 0;
  if (msg.text) {
    const bubble = h("div", { class: "bubble" }, md(msg.text));
    if (animate && msg.role === "assistant") textMs = revealWords(bubble);
    wrap.append(bubble);
  }
  let n = 0;
  for (const c of msg.components || []) {
    const el = renderComponent(c);
    if (!el) continue;
    el.dataset.type = c.type;
    if (c.type === "model_cards") el.dataset.hint = c.cards.map((x) => x.name.replace(/^BMW /, "")).join(", ");
    if (animate) { el.classList.add("rise"); el.style.animationDelay = `${Math.round(textMs * 0.6 + 120 + n++ * 110)}ms`; }
    wrap.append(el);
  }
  els.messages.append(wrap);
  if (msg.role === "user") document.body.classList.add("started");
  scroll(animate && msg.role === "assistant" ? wrap : null);
}

const scroll = (reply = null) => requestAnimationFrame(() => {
  if (reply) {
    // Glide to the new reply, but never past its first line: long answers are read from the top.
    // scrollIntoView handles both the chat panel and the page (which scrolls on small screens).
    reply.scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
    return;
  }
  els.scroll.scrollTop = els.scroll.scrollHeight;
  // On small screens in discover mode the page itself scrolls; keep the composer in view.
  if (layout !== "configure" && window.matchMedia("(max-width: 1000px)").matches) els.form.scrollIntoView({ block: "end" });
});

function markDone(el) {
  el.classList.add("done");
  el.querySelectorAll("button, input").forEach((b) => { b.disabled = true; });
}

function renderComponent(c) {
  const fn = COMPONENTS[c.type];
  return fn ? fn(c) : null;
}

const COMPONENTS = {
  question(c) {
    const el = h("div", { class: "comp question" }, `<p>${esc(c.prompt)}</p>`);
    const row = h("div", { class: "choices" });
    c.choices.forEach((ch) => row.append(h("button", {
      class: "choice",
      onclick: () => { markDone(el); act({ type: "answer", value: ch.label }, ch.label); },
    }, esc(ch.label))));
    el.append(row);
    return el;
  },

  slider(c) {
    const el = h("div", { class: "comp slider" }, `<p>${esc(c.prompt)}</p>`);
    const input = h("input", { type: "range", min: 0, max: 100, value: Math.round(c.value * 100), "aria-label": t("comfort_vs_sporty") });
    const row = h("div", { class: "slider-row" });
    row.append(h("span", {}, esc(c.left_label)), input, h("span", {}, esc(c.right_label)));
    const apply = h("button", {
      class: "btn primary small",
      onclick: () => { markDone(el); act({ type: "set_preference", key: c.preference, value: input.value / 100 }, t("preference_echo", { pct: input.value })); },
    }, t("apply"));
    el.append(row, apply);
    return el;
  },

  model_cards(c) {
    const el = h("div", { class: "comp" }, `<h3>${esc(c.title)}</h3>`);
    const grid = h("div", { class: "cards" });
    const best = c.cards.findIndex((x) => x.fits);
    c.cards.forEach((card, i) => {
      const status = card.fits ? `<span class="status ok">${t("meets_needs")}</span>`
        : `<span class="status warn" title="${esc(card.violations.join("; "))}">${esc(card.violations[0] || t("needs_compromise"))}</span>`;
      const item = h("article", { class: "model-card", title: card.reasons.join(" · ") }, `
        <p class="kicker">${esc(BODY()[card.body] || card.body)} · ${esc(card.powertrain)}</p>
        <h4>${esc(card.name.replace(/^BMW /, ""))}</h4>
        <div class="car">${carVisual(card.model_id, card.body, card.name)}</div>
        <div class="price">${t("from")} <strong>${eur(card.entry_price)}</strong></div>
        <p class="facts">${card.highlights.slice(0, 3).map(esc).join(" · ")}</p>
        ${status}`);
      item.append(h("button", {
        class: `btn ${i === best ? "primary" : "secondary"}`,
        onclick: () => act({ type: "select_model", model_id: card.model_id }, t("configure_the", { name: card.name })),
      }, t("configure")));
      grid.append(item);
    });
    el.append(grid);
    return el;
  },

  comparison(c) {
    const head = c.models.map((m) => `<th>${esc(m.name)}</th>`).join("");
    const rows = c.rows.map((r) => `<tr><th>${esc(r.label)}</th>${r.values.map((v, i) =>
      `<td class="${i === r.best_index ? "best" : ""}">${esc(v)}</td>`).join("")}</tr>`).join("");
    const el = h("div", { class: "comp" }, `<h3>${t("side_by_side")}</h3><div class="table-wrap"><table class="compare"><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`);
    const btns = h("div", { class: "choices" });
    c.models.forEach((m) => btns.append(h("button", {
      class: "btn secondary small", onclick: () => act({ type: "select_model", model_id: m.model_id }, t("configure_the", { name: m.name })),
    }, t("configure_short", { name: esc(m.name.replace("BMW ", "")) }))));
    el.append(btns);
    return el;
  },

  tradeoffs(c) {
    const el = h("div", { class: "comp tradeoffs" }, `<h3>${esc(c.title)}</h3>`);
    c.items.forEach((item) => {
      const model = (item.description.match(/^(BMW [^(]+?) (?:would fit|würde passen)/) || [])[1] || "";
      const row = h("div", { class: "tradeoff", title: item.description },
        `<span>${esc(item.label)}${model ? ` <span class="muted">→ ${esc(model.replace(/^BMW /, ""))}</span>` : ""}</span>`);
      row.append(h("button", {
        class: "text-link",
        onclick: () => { markDone(el); act({ type: "apply_tradeoff", patch: item.patch, label: item.label }, t("accept_echo", { label: item.label })); },
      }, t("accept")));
      el.append(row);
    });
    return el;
  },

  option_toggles(c) {
    const el = h("div", { class: "comp" }, `<h3>${esc(c.title)}</h3>`);
    c.options.slice(0, 4).forEach((o) => el.append(optionRow(o, true)));
    if (c.options.length > 4) el.append(h("p", { class: "muted small-note" }, t("more_options")));
    return el;
  },

  conflict(c) {
    if (layout === "configure") {
      return h("div", { class: "comp notice warning" }, t("not_possible_inline", { message: esc(c.message) }));
    }
    const el = h("div", { class: "comp conflict" }, `<p><strong>${t("not_possible")}</strong> ${esc(c.message)}</p>`);
    const row = h("div", { class: "choices" });
    c.resolutions.forEach((r) => row.append(h("button", {
      class: r.change ? "btn primary small" : "btn secondary small",
      onclick: () => {
        markDone(el);
        if (r.change) changeOption(r.change.action, r.change.option_id, r.change.force);
        else renderMessage({ role: "user", text: r.label, components: [] });
      },
    }, esc(r.label))));
    el.append(row);
    return el;
  },

  notice(c) {
    return h("div", { class: `comp notice ${c.level}` }, esc(c.text));
  },

  summary(c) {
    const lines = c.lines.filter((l) => l.status !== "standard").map((l) =>
      `<tr><td>${esc(l.name)}<div class="why">${esc(l.reason)}</div></td><td class="num">${l.price ? eur(l.price) : t("incl")}</td></tr>`).join("");
    const budget = c.budget.max != null
      ? `<p class="check ${c.budget.over_by ? "bad" : "good"}">${c.budget.over_by ? t("over_budget_by", { amount: eur(c.budget.over_by) }) : t("under_budget_by", { amount: eur(c.budget.remaining) })} ${t("your_budget", { amount: eur(c.budget.max) })}</p>` : "";
    const unmet = c.unmet_requirements.length
      ? `<ul class="violations">${c.unmet_requirements.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>`
      : `<p class="check good">${t("meets_all", { list: c.requirements.map(esc).join(" · ") })}</p>`;
    const s = c.specs;
    const facts = [POWERTRAIN()[s.powertrain], s.electric_range_km ? t("km_electric", { km: num(s.electric_range_km) }) : t("km_range", { km: num(s.total_range_km) }),
      t("seats_n", { n: s.seats }), t("boot_l", { l: s.trunk_l }), s.tow_kg ? t("tows_kg", { kg: num(s.tow_kg) }) : ""].filter(Boolean);
    return h("div", { class: "comp summary" }, `
      <div class="summary-head"><div><p class="eyebrow">${t("your_configuration")}</p><h3>${esc(c.model_name)}</h3></div>
        <span class="tag ${c.valid ? "dark" : "outline"}">${c.valid ? t("valid") : t("needs_attention")}</span></div>
      <div class="car">${carVisual(c.model_id, s.body, c.model_name)}</div>
      <div class="facts">${facts.map((f) => `<span>${esc(f)}</span>`).join("")}</div>
      <table class="lines"><tr><td>${t("base_price")}</td><td class="num">${eur(c.base_price)}</td></tr>${lines}
        <tr class="total"><td>${t("total_price")}</td><td class="num">${eur(c.total_price)}</td></tr></table>
      ${budget}${unmet}
      ${c.assumptions.length ? `<details><summary>${t("assumptions")}</summary><ul>${c.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""}`);
  },
};

// ------------------------------------------------------------------ option rows (chat + panel)

function optionRow(o, compact = false) {
  const locked = o.state === "standard" || o.state === "included";
  const on = o.state === "selected" || locked;
  const row = h("label", { class: `opt ${o.state}`, title: [o.recommended_reason, o.note || o.description].filter(Boolean).join(" · ") });
  const box = h("input", { type: "checkbox", checked: on, disabled: locked, "data-opt": o.id });
  box.addEventListener("change", () => {
    const wasOn = !box.checked;
    box.checked = wasOn; // the server is the source of truth; state is re-synced from the response
    changeOption(wasOn ? "remove" : "add", o.id);
  });
  const detail = o.state === "unavailable" ? o.note
    : o.state === "included" || o.state === "standard" ? o.note
    : "";
  const rec = o.recommended && !compact ? `<span class="tag rec">${t("suggested")}</span>` : "";
  row.append(box, h("span", { class: "opt-name" }, `${esc(o.name)}${rec}${detail ? `<small>${esc(detail)}</small>` : ""}`),
    h("span", { class: "opt-price" }, o.state === "included" || o.state === "standard" ? t("incl") : eur(o.price)));
  return row;
}

// ------------------------------------------------------------------ side panel

function renderNeeds(container, state, removable = true, onStage = false) {
  container.innerHTML = "";
  if (!state.requirements.length) {
    container.innerHTML = onStage ? `<span class="muted">${t("none_yet")}</span>` : `<p class="muted">${t("nothing_yet")}</p>`;
  }
  state.requirements.forEach((r) => {
    const chip = h("span", { class: "chip" }, esc(r.label));
    if (removable) chip.append(h("button", {
      class: "x", title: t("remove_requirement"), "aria-label": t("remove_x", { label: r.label }),
      onclick: () => onStage
        ? updateNeeds({ [r.field]: null })
        : act({ type: "remove_requirement", field: r.field }, t("remove_echo", { label: r.label })),
    }, "×"));
    container.append(chip);
  });
}

function renderState(state) {
  lastState = state;
  renderNeeds(els.needs, state);
  els.needsBar.hidden = !state.requirements.length;
  els.assumptionsBox.hidden = !state.assumptions.length;
  els.assumptions.innerHTML = state.assumptions.map((a) => `<li>${esc(a)}</li>`).join("");

  const v = state.configuration;
  setLayout(v ? "configure" : "discover");
  if (!v) return;
  renderStage(v, state);

  // keep option toggles shown inside the chat in sync with the authoritative configuration
  const byId = Object.fromEntries(v.catalog_options.map((o) => [o.id, o]));
  els.messages.querySelectorAll("input[data-opt]").forEach((box) => {
    const o = byId[box.dataset.opt];
    if (!o) return;
    box.checked = ["selected", "included", "standard"].includes(o.state);
    // Names follow the current language, also in rows shown before a language switch.
    const name = box.closest(".opt")?.querySelector(".opt-name")?.firstChild;
    if (name?.nodeType === Node.TEXT_NODE) name.nodeValue = o.name;
  });
}

// ------------------------------------------------------------------ layout modes

let layout = "discover";
let chatMinimized = false;

function setLayout(mode) {
  const entering = mode === "configure" && layout !== "configure";
  layout = mode;
  document.body.classList.toggle("mode-configure", mode === "configure");
  // The stage stays in the DOM so the layout change can be animated (see styles.css).
  els.stage.setAttribute("aria-hidden", String(mode !== "configure"));
  if (entering) {
    els.stage.scrollTop = 0;
    // On small screens the stage needs the room: start with the assistant minimized.
    setChatMinimized(window.matchMedia("(max-width: 1000px)").matches);
  }
  if (mode !== "configure") setChatMinimized(false);
}

function setChatMinimized(on) {
  const reopening = chatMinimized && !on;
  chatMinimized = on;
  document.body.classList.toggle("chat-min", on);
  els.fab.hidden = !(on && layout === "configure");
  if (!on) els.fab.classList.remove("has-new");
  // Only jump to the latest message when the chat is actually reopened; this also runs on every
  // state update, and must not undo the scroll that keeps a new reply's first line in view.
  if (reopening) scroll([...els.messages.querySelectorAll(".msg.assistant")].pop());
}

// ------------------------------------------------------------------ vehicle stage (configure mode)

let activeCat = null;
const openNotOffered = new Set();  // categories whose "not available" list is expanded

function renderStage(v, state) {
  const sp = v.specs;
  const b = v.budget;
  const pct = b.max ? Math.min(100, Math.round((v.total_price / b.max) * 100)) : 0;
  const ok = v.valid && !v.unmet_requirements.length;
  const groups = {};
  v.catalog_options.forEach((o) => { (groups[o.category] ||= []).push(o); });
  const cats = Object.keys(groups);
  if (!activeCat || !groups[activeCat]) {
    activeCat = cats.find((c) => groups[c].some((o) => o.recommended)) || cats[0];
  }
  const rangeLabel = sp.powertrain === "bev" ? t("electric_range") : t("total_range");
  const range = num(sp.powertrain === "bev" ? sp.electric_range_km : sp.total_range_km);

  els.stage.innerHTML = `
    <div class="stage-inner">
      <header class="stage-head">
        <div>
          <p class="kicker">${esc(BODY()[sp.body] || sp.body)} · ${esc(POWERTRAIN()[sp.powertrain])}</p>
          <h1>${esc(v.model_name)}</h1>
          <p class="status ${ok ? "ok" : "warn"}">${ok ? t("valid_meets_all") : esc([...v.issues.map((i) => i.message), ...v.unmet_requirements.map((u) => u.message)][0] || t("needs_attention"))}</p>
        </div>
        <div class="stage-price">
          <span>${t("total_price")}</span>
          <strong>${eur(v.total_price)}</strong>
          ${b.max ? `<div class="budget-bar ${b.over_by ? "over" : ""}"><div></div></div>
            <span class="budget-note ${b.over_by ? "over" : ""}">${b.over_by ? t("over_your_budget", { amount: eur(b.over_by) }) : t("left_of", { amount: eur(b.remaining), max: eur(b.max) })}</span>` : ""}
        </div>
      </header>
      <div class="stage-car">${carVisual(v.model_id, sp.body, v.model_name)}</div>
      <dl class="stage-specs">
        <div><dt>${rangeLabel}</dt><dd>${range} km</dd></div>
        <div><dt>0–100 km/h</dt><dd>${lang() === "de" ? String(sp.acceleration_s).replace(".", ",") : sp.acceleration_s} s</dd></div>
        <div><dt>${t("seats")}</dt><dd>${sp.seats}</dd></div>
        <div><dt>${t("boot")}</dt><dd>${sp.trunk_l} l</dd></div>
      </dl>
      <section class="stage-needs-box">
        <div class="stage-needs"><span class="label">${t("your_needs")}</span><div class="chips" id="stage-needs"></div>
          <button type="button" class="link-btn" id="needs-adjust" aria-expanded="${needsDraft ? "true" : "false"}">${needsDraft ? t("close") : t("adjust")}</button></div>
        <div id="needs-editor"></div>
      </section>
      <nav class="tabs" role="tablist"></nav>
      <div class="tiles" role="tabpanel"></div>
      <div class="stage-actions"><button class="btn primary" type="button" id="review">${t("review_summary")}</button></div>
    </div>`;

  const fill = els.stage.querySelector(".budget-bar div");
  if (fill) fill.style.width = `${pct}%`; // set via CSSOM: the CSP forbids inline style attributes
  renderNeeds(els.stage.querySelector("#stage-needs"), state, true, true);
  els.stage.querySelector("#needs-adjust").addEventListener("click", () => {
    needsDraft = needsDraft ? null : structuredClone(state.requirement_values);
    rerenderStage();
    if (needsDraft) els.stage.querySelector("#needs-editor input, #needs-editor button")?.focus();
  });
  if (needsDraft) els.stage.querySelector("#needs-editor").append(needsEditor(state.requirement_values));

  const tabs = els.stage.querySelector(".tabs");
  const tiles = els.stage.querySelector(".tiles");
  const showCat = (cat) => {
    activeCat = cat;
    tabs.querySelectorAll("button").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.cat === cat)));
    tiles.innerHTML = "";
    const offered = groups[cat].filter((o) => o.state !== "unavailable");
    const notOffered = groups[cat].filter((o) => o.state === "unavailable");
    offered.forEach((o) => tiles.append(optionTile(o)));
    if (notOffered.length) {
      // Options this model doesn't offer stay out of the way, one click away for reference.
      const more = h("details", { class: "not-offered", open: openNotOffered.has(cat) || undefined },
        `<summary>${t("not_offered", { n: notOffered.length })}</summary>`);
      more.addEventListener("toggle", () => { more.open ? openNotOffered.add(cat) : openNotOffered.delete(cat); });
      const list = h("div", { class: "tiles" });
      notOffered.forEach((o) => list.append(optionTile(o)));
      more.append(list);
      tiles.append(more);
    }
  };
  for (const cat of cats) {
    const flagged = groups[cat].some((o) => conflictIds.has(o.id));
    tabs.append(h("button", { type: "button", role: "tab", "data-cat": cat, class: flagged ? "conflicting" : "", onclick: () => showCat(cat) },
      esc(cat)));
  }
  showCat(activeCat);
  els.stage.querySelector("#review").addEventListener("click", () => {
    if (chatMinimized) setChatMinimized(false);
    act({ type: "request_summary" }, t("show_summary"));
  });
}

function optionTile(o) {
  const locked = o.state === "standard" || o.state === "included";
  const on = o.state === "selected" || locked;
  const note = o.state === "unavailable" || locked ? o.note : "";
  const marks = `${conflictIds.has(o.id) ? " conflicting" : ""}${flashIds.has(o.id) ? " flash" : ""}`;
  const tile = h("button", {
    type: "button", class: `tile ${o.state}${on ? " on" : ""}${marks}`, disabled: locked || undefined, "data-opt": o.id,
    title: [o.recommended_reason, o.description].filter(Boolean).join(" · "), "aria-pressed": String(on),
  }, `<span class="tile-check" aria-hidden="true"></span>
     <span class="tile-name">${esc(o.name)}${o.recommended && !on ? `<span class="tag rec">${t("suggested")}</span>` : ""}</span>
     ${note ? `<span class="tile-note">${esc(note)}</span>` : ""}
     <span class="tile-price">${locked ? t("incl") : eur(o.price)}</span>`);
  tile.addEventListener("click", () => {
    changeOption(on ? "remove" : "add", o.id);
  });
  return tile;
}

// ------------------------------------------------------------------ needs editor (stage)

let needsDraft = null;  // requirement values being edited on the stage; null = editor closed

const updateNeeds = (patch) =>
  send({ action: { type: "update_requirements", patch } }, null, { silent: true });

const TOWING = () => [[null, t("not_needed")], [0, t("bike_carrier")], ...[750, 1500, 2000].map((kg) => [kg, `${num(kg)} kg`])];

function needsEditor(saved) {
  const d = needsDraft;
  const powertrainMode = d.powertrain_required.length ? "required" : "preferred";
  const powertrains = d.powertrain_required.length ? d.powertrain_required : d.powertrain_preferred;
  const towing = TOWING().some(([v]) => v === d.towing_kg) ? TOWING() : [...TOWING(), [d.towing_kg, `${num(d.towing_kg)} kg`]];
  const numOrNull = (v) => (v === "" || v == null ? null : Number(v));
  const toggles = (name, labels, chosen) => Object.entries(labels).map(([k, label]) =>
    `<button type="button" class="pick" data-${name}="${k}" aria-pressed="${chosen.includes(k)}">${esc(label)}</button>`).join("");
  const sport = d.sportiness == null ? null : Math.round(d.sportiness * 100);

  const form = h("form", { class: "needs-editor", "aria-label": t("adjust_needs") }, `
    <label class="field"><span>${t("budget_up_to")}</span>
      <input name="budget_max" type="number" min="0" step="1000" inputmode="numeric" placeholder="${t("no_limit")}" value="${d.budget_max ?? ""}"></label>
    <div class="field wide"><span>${t("powertrain")}
        <select name="pt_mode" aria-label="${t("powertrain_strictness")}">
          <option value="preferred" ${powertrainMode === "preferred" ? "selected" : ""}>${t("preferred")}</option>
          <option value="required" ${powertrainMode === "required" ? "selected" : ""}>${t("required")}</option></select></span>
      <div class="picks">${toggles("pt", POWERTRAIN(), powertrains)}</div></div>
    <div class="field wide"><span>${t("body_style")}</span><div class="picks">${toggles("body", BODY(), d.body_styles)}</div></div>
    <label class="field"><span>${t("seats_at_least")}</span>
      <input name="min_seats" type="number" min="2" max="9" placeholder="${t("any")}" value="${d.min_seats ?? ""}"></label>
    <label class="field"><span>${t("child_seats")}</span>
      <input name="child_seats" type="number" min="0" max="6" placeholder="${t("none")}" value="${d.child_seats || ""}"></label>
    <label class="field"><span>${t("boot_at_least")}</span>
      <input name="min_trunk_l" type="number" min="0" max="2000" step="10" placeholder="${t("any")}" value="${d.min_trunk_l ?? ""}"></label>
    <label class="field"><span>${t("towing")}</span><select name="towing_kg">
      ${towing.map(([v, label]) => `<option value="${v ?? ""}" ${v === d.towing_kg ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></label>
    <label class="field check"><input name="long_distance" type="checkbox" ${d.long_distance ? "checked" : ""}><span>${t("long_distance")}</span></label>
    <div class="field wide"><span>${t("comfort_or_sport")} <output>${sport == null ? t("no_preference") : t("pct_sporty", { pct: sport })}</output></span>
      <input name="sportiness" type="range" min="0" max="100" step="5" value="${sport ?? 50}" aria-label="${t("comfort_to_sport")}"></div>
    <div class="editor-actions">
      <button type="button" class="btn secondary small" data-cancel>${t("cancel")}</button>
      <button type="submit" class="btn primary small">${t("apply")}</button></div>`);

  const read = () => {
    const f = form.elements;
    const pts = [...form.querySelectorAll("[data-pt][aria-pressed=true]")].map((b) => b.dataset.pt);
    const required = f.pt_mode.value === "required";
    Object.assign(needsDraft, {
      budget_max: numOrNull(f.budget_max.value), min_seats: numOrNull(f.min_seats.value),
      child_seats: numOrNull(f.child_seats.value) || null, min_trunk_l: numOrNull(f.min_trunk_l.value),
      towing_kg: numOrNull(f.towing_kg.value), long_distance: f.long_distance.checked,
      powertrain_required: required ? pts : [], powertrain_preferred: required ? [] : pts,
      body_styles: [...form.querySelectorAll("[data-body][aria-pressed=true]")].map((b) => b.dataset.body),
    });
  };
  form.addEventListener("click", (e) => {
    const pick = e.target.closest(".pick");
    if (pick) { pick.setAttribute("aria-pressed", String(pick.getAttribute("aria-pressed") !== "true")); read(); }
    if (e.target.closest("[data-cancel]")) { needsDraft = null; rerenderStage(); }
  });
  form.addEventListener("change", read);  // keep the draft if the stage re-renders while editing
  form.addEventListener("input", (e) => {
    if (e.target.name === "sportiness") {
      needsDraft.sportiness = Number(e.target.value) / 100;
      form.querySelector("output").textContent = t("pct_sporty", { pct: e.target.value });
    }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    read();
    const patch = {};
    for (const [k, v] of Object.entries(needsDraft)) {
      if (JSON.stringify(v) !== JSON.stringify(saved[k])) patch[k] = v;
    }
    needsDraft = null;
    if (Object.keys(patch).length) updateNeeds(patch); else rerenderStage();
  });
  return form;
}

function showNeedsFeedback(fb) {
  if (fb.status === "rejected") { toast(fb.error || t("needs_not_saved"), "warning"); return; }
  if (fb.status === "noop") return;
  if (fb.unmet.length) toast(t("needs_unmet", { list: fb.unmet.join("; ") }), "warning");
  else toast(t("needs_ok"), "ok");
}

// ------------------------------------------------------------------ option-change feedback (stage)

let conflictIds = new Set();   // options involved in an open conflict (outlined on the stage)
let flashIds = new Set();      // options that just changed (brief highlight)
let lastState = null;

function showFeedback(fb) {
  if (fb.kind === "language") return;
  if (fb.kind === "requirements") { showNeedsFeedback(fb); return; }
  if (fb.status === "conflict" && fb.conflict) { openConflict(fb.conflict); return; }
  if (fb.status === "rejected") { toast(fb.error || t("change_impossible"), "warning"); return; }
  if (fb.status === "noop") { toast(fb.notes.join(" "), "info"); return; }
  // Short confirmation: skip items that simply went with a removed package, drop the reasons.
  const lines = fb.notes
    .filter((n) => !/: (?:comes with|gehört zu) |would replace| statt /.test(n))
    .map((n) => n.replace(/^(Removed [^:]+|[^:]+ entfernt):.*$/, "$1."));
  toast(lines.join(" ") || t("updated"), "ok");
  flashIds = new Set(fb.changed);
  rerenderStage();
  setTimeout(() => { flashIds = new Set(); rerenderStage(); }, 1400);
}

function rerenderStage() {
  if (lastState?.configuration && layout === "configure") renderStage(lastState.configuration, lastState);
}

function openConflict(c) {
  document.querySelector(".dialog-backdrop")?.remove();
  conflictIds = new Set(c.option_ids || []);
  // Show the tab of the option that caused the conflict, so its tile is visibly outlined.
  const trigger = lastState?.configuration?.catalog_options.find((o) => o.id === (c.option_ids || [])[0]);
  if (trigger) activeCat = trigger.category;
  rerenderStage();
  const close = () => { backdrop.remove(); conflictIds = new Set(); rerenderStage(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const backdrop = h("div", { class: "dialog-backdrop" });
  const dialog = h("div", { class: "dialog", role: "alertdialog", "aria-modal": "true", "aria-labelledby": "dlg-title" },
    `<p class="dialog-kicker">${t("conflict")}</p><h2 id="dlg-title">${t("not_possible_title")}</h2><p>${esc(c.message)}</p>`);
  const row = h("div", { class: "dialog-actions" });
  c.resolutions.forEach((r) => row.append(h("button", {
    type: "button", class: `btn ${r.change ? "primary" : "secondary"}`,
    onclick: () => { close(); if (r.change) changeOption(r.change.action, r.change.option_id, r.change.force); },
  }, esc(r.label))));
  dialog.append(row);
  backdrop.append(dialog);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", onKey);
  document.body.append(backdrop);
  row.querySelector("button")?.focus();
}

let toastTimer = null;
function toast(text, level = "info") {
  let el = document.querySelector(".toast");
  if (!el) { el = h("div", { class: "toast", role: "status", "aria-live": "polite" }); document.body.append(el); }
  el.className = `toast ${level} show`;
  el.textContent = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), level === "warning" || level === "error" ? 6000 : 4000);
}

// ------------------------------------------------------------------ voice
// Hands-free: the microphone stays open, each utterance becomes a chat message, replies are read
// out, and talking over a reply stops it. Speech recognition and synthesis go through the agent.

const VOICE_LABEL = { starting: "v_starting", listening: "v_listening", hearing: "v_listening", thinking: "v_thinking", speaking: "v_speaking" };
let voiceState = "off";

async function voiceRequest(path, init) {
  const res = await fetch(`${API}/sessions/${sessionId}/voice/${path}`, init);
  if (res.status === 401) { location.replace("/login.html"); throw new Error(t("sign_in_please")); }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : t("voice_failed", { status: res.status }));
  }
  return res;
}

const whenIdle = async () => { while (busy) await new Promise((r) => setTimeout(r, 100)); };

const voice = new VoiceMode({
  transcribe: async (wav) => (await (await voiceRequest("transcribe", {
    method: "POST", headers: { "content-type": "audio/wav" }, body: wav })).json()).text,
  synthesize: async (text, signal) => (await voiceRequest("speech", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }), signal,
  })).arrayBuffer(),
  onUtterance: async (text) => { await whenIdle(); await say(text); },
  onState: (state) => { voiceState = state; renderVoiceState(); },
  onLevel: (level) => els.voiceStatus.style.setProperty("--level", level.toFixed(2)),
  onError: (key, detail) => toast(detail || t(key), "error"),
});

function renderVoiceState() {
  const on = voiceState !== "off";
  document.body.classList.toggle("voice-on", on);
  els.voice.setAttribute("aria-pressed", String(on));
  els.voice.title = on ? t("end_talk") : t("talk");
  els.voice.setAttribute("aria-label", els.voice.title);
  els.voiceStatus.hidden = !on;
  els.voiceStatus.dataset.state = voiceState;
  els.voiceLabel.textContent = VOICE_LABEL[voiceState] ? t(VOICE_LABEL[voiceState]) : "";
}

function setVoiceAvailable(available) {
  els.voice.hidden = !(available && voiceSupported());
  if (els.voice.hidden && voice.active) voice.stop();
}

els.voice.addEventListener("click", () => (voice.active ? voice.stop() : voice.start()));
els.voiceStop.addEventListener("click", () => voice.stop());
window.addEventListener("pagehide", () => voice.stop());

// ------------------------------------------------------------------ wiring

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.input.value.trim();
  if (!text) return;
  els.input.value = "";
  say(text);
});
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); els.form.requestSubmit(); }
});
els.chatMin.addEventListener("click", () => setChatMinimized(true));
els.fab.addEventListener("click", () => setChatMinimized(false));
els.newSession.addEventListener("click", () => { if (!busy) startSession().catch((e) => renderError(e.message)); });

applyStatic();
mountSwitch($(".topbar-actions"), (code) => {
  renderVoiceState();
  if (lastState?.configuration) needsDraft = null;
  switchLanguage(code).catch((e) => toast(e.message, "error"));
});

// Optional brand assets: assets/manifest.json lists what exists (generated at image build time).
const LOGO_TYPES = /\.(svg|png|webp|jpe?g)$/i;
const FONT_FORMATS = { woff2: "woff2", woff: "woff", otf: "opentype", ttf: "truetype" };
const FONT_WEIGHTS = [  // matched against the file name, most specific first
  [/extra-?light|ultra-?light/i, "200"], [/thin|hairline/i, "100"], [/light/i, "300"], [/medium/i, "500"],
  [/semi-?bold|demi/i, "600"], [/extra-?bold|black|heavy/i, "800"], [/bold/i, "700"], [/regular|normal|book|roman/i, "400"],
];

async function loadBrandAssets() {
  let files = [];
  try {
    const res = await fetch("assets/manifest.json");
    if (res.ok) files = await res.json();
  } catch { return; }

  for (const f of files) {
    const m = f.match(/^cars\/([a-z0-9_]+)\.(webp|png|jpe?g|avif)$/i);
    if (m) CAR_PHOTOS.set(m[1], `assets/${f}`);
  }
  const logo = files.find((f) => f.startsWith("logo.") && LOGO_TYPES.test(f));
  if (logo) {
    const img = $("#logo");
    img.addEventListener("load", () => { img.hidden = false; document.body.classList.add("has-logo"); }, { once: true });
    img.src = `assets/${encodeURI(logo)}`;
  }

  // One weight per file, preferring web formats when the same weight exists twice.
  const order = ["woff2", "woff", "otf", "ttf"];
  const byWeight = new Map();
  for (const f of files.filter((x) => x.startsWith("fonts/"))) {
    const ext = f.split(".").pop().toLowerCase();
    if (!FONT_FORMATS[ext]) continue;
    const weight = (FONT_WEIGHTS.find(([re]) => re.test(f.split("/").pop())) || [null, "400"])[1];
    const current = byWeight.get(weight);
    if (!current || order.indexOf(ext) < order.indexOf(current.split(".").pop().toLowerCase())) byWeight.set(weight, f);
  }
  const loads = [...byWeight].map(([weight, f]) => {
    const ext = f.split(".").pop().toLowerCase();
    return new FontFace("BMW Brand", `url(assets/${encodeURI(f)}) format("${FONT_FORMATS[ext]}")`, { weight }).load()
      .then((face) => { document.fonts.add(face); return true; }).catch(() => false);
  });
  if ((await Promise.all(loads)).some(Boolean)) document.documentElement.classList.add("brand-font");
}

// Load the asset manifest first so the first render already uses photos, logo and font.
loadBrandAssets().finally(() => restoreSession().catch((e) => renderError(t("unreachable", { error: e.message }), () => location.reload())));
