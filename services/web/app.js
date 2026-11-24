// BMW Configurator Assistant - web client.
// Renders the agent's messages and adaptive UI components; every user interaction is sent
// back to the agent service as either a free-text message or a structured action.

const API = "/api";
const $ = (sel) => document.querySelector(sel);
const els = {
  messages: $("#messages"), scroll: $("#scroll"), form: $("#composer"), input: $("#input"), send: $("#send"),
  mode: $("#mode"), needs: $("#needs"), assumptions: $("#assumptions"),
  assumptionsBox: $("#assumptions-box"), config: $("#config"), newSession: $("#new-session"),
};

let sessionId = null;
let busy = false;

// ------------------------------------------------------------------ utils

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
const eur = (v) => "€" + Number(v).toLocaleString("en-US");
const POWERTRAIN = { bev: "Electric", phev: "Plug-in hybrid", petrol: "Petrol", diesel: "Diesel" };
const BODY = { sav: "SAV", touring: "Touring", gran_coupe: "Gran Coupé", tourer: "Active Tourer", sedan: "Sedan" };

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
  if (!res.ok) {
    const err = new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return body;
}

// ------------------------------------------------------------------ session

async function startSession() {
  const body = await api("/sessions", { method: "POST" });
  sessionId = body.session_id;
  try { localStorage.setItem("sessionId", sessionId); } catch { /* storage unavailable */ }
  els.messages.innerHTML = "";
  document.body.classList.remove("started");
  setMode(body.mode);
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
    setMode(body.mode);
    els.messages.innerHTML = "";
    body.transcript.forEach((m) => renderMessage(m));
    renderState(body.state);
  } catch {
    await startSession();
  }
}

const MODE_LABELS = { openai: "AI agent (OpenAI)", anthropic: "AI agent (Claude)", guided: "Guided mode (offline)" };

function setMode(mode) {
  els.mode.textContent = MODE_LABELS[mode] || mode;
  els.mode.className = "mode " + mode;
}

async function send(payload, echo) {
  if (busy) return;
  busy = true;
  setBusy(true);
  if (echo) renderMessage({ role: "user", text: echo, components: [] });
  const typing = showTyping();
  try {
    const body = await api(`/sessions/${sessionId}/turn`, { method: "POST", body: JSON.stringify(payload) });
    typing.remove();
    setMode(body.mode);
    renderMessage(body.message);
    renderState(body.state);
  } catch (err) {
    typing.remove();
    if (err.status === 404) {
      renderError("Your session expired. Starting a new one…");
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
  const el = h("div", { class: "msg assistant error" }, esc(text) + " ");
  if (retry) el.append(h("button", { class: "link", onclick: () => { el.remove(); retry(); } }, "Retry"));
  els.messages.append(el);
  scroll();
}

// Only the latest assistant message keeps its full UI. Older ones are condensed so the
// conversation stays lean: answered/stale prompts disappear, bigger blocks fold into one line.
const TRANSIENT = ["question", "slider", "conflict", "tradeoffs", "notice"];
const FOLD_LABEL = { model_cards: "suggested models", comparison: "comparison", option_toggles: "suggested options", summary: "summary" };

function condensePrevious() {
  els.messages.querySelectorAll(".msg.assistant:not(.condensed)").forEach((msg) => {
    msg.classList.add("condensed");
    msg.querySelectorAll(":scope > .comp").forEach((comp) => {
      const type = comp.dataset.type;
      if (TRANSIENT.includes(type)) { comp.remove(); return; }
      const fold = h("details", { class: "fold" }, `<summary>Show earlier ${FOLD_LABEL[type] || "details"}${comp.dataset.hint ? `: ${esc(comp.dataset.hint)}` : ""}</summary>`);
      comp.replaceWith(fold);
      fold.append(comp);
    });
  });
}

function renderMessage(msg) {
  if (msg.role === "assistant") condensePrevious();
  const wrap = h("div", { class: `msg ${msg.role}` });
  if (msg.text) wrap.append(h("div", { class: "bubble" }, md(msg.text)));
  for (const c of msg.components || []) {
    const el = renderComponent(c);
    if (!el) continue;
    el.dataset.type = c.type;
    if (c.type === "model_cards") el.dataset.hint = c.cards.map((x) => x.name.replace(/^BMW /, "")).join(", ");
    wrap.append(el);
  }
  els.messages.append(wrap);
  if (msg.role === "user") document.body.classList.add("started");
  scroll();
}

const scroll = () => requestAnimationFrame(() => {
  els.scroll.scrollTop = els.scroll.scrollHeight;
  if (window.matchMedia("(max-width: 1000px)").matches) els.form.scrollIntoView({ block: "end" });
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
    const input = h("input", { type: "range", min: 0, max: 100, value: Math.round(c.value * 100), "aria-label": "Comfort versus sporty" });
    const row = h("div", { class: "slider-row" });
    row.append(h("span", {}, esc(c.left_label)), input, h("span", {}, esc(c.right_label)));
    const apply = h("button", {
      class: "btn primary small",
      onclick: () => { markDone(el); act({ type: "set_preference", key: c.preference, value: input.value / 100 }, `Preference: ${input.value}% sporty`); },
    }, "Apply");
    el.append(row, apply);
    return el;
  },

  model_cards(c) {
    const el = h("div", { class: "comp" }, `<h3>${esc(c.title)}</h3>`);
    const grid = h("div", { class: "cards" });
    const best = c.cards.findIndex((x) => x.fits);
    c.cards.forEach((card, i) => {
      const status = card.fits ? `<span class="status ok">Meets your needs</span>`
        : `<span class="status warn" title="${esc(card.violations.join("; "))}">${esc(card.violations[0] || "Needs a compromise")}</span>`;
      const item = h("article", { class: "model-card", title: card.reasons.join(" · ") }, `
        <p class="kicker">${esc(BODY[card.body] || card.body)} · ${esc(card.powertrain)}</p>
        <h4>${esc(card.name.replace(/^BMW /, ""))}</h4>
        <div class="car">${carVisual(card.model_id, card.body, card.name)}</div>
        <div class="price">from <strong>${eur(card.entry_price)}</strong></div>
        <p class="facts">${card.highlights.slice(0, 3).map(esc).join(" · ")}</p>
        ${status}`);
      item.append(h("button", {
        class: `btn ${i === best ? "primary" : "secondary"}`,
        onclick: () => act({ type: "select_model", model_id: card.model_id }, `Configure the ${card.name}`),
      }, "Configure"));
      grid.append(item);
    });
    el.append(grid);
    return el;
  },

  comparison(c) {
    const head = c.models.map((m) => `<th>${esc(m.name)}</th>`).join("");
    const rows = c.rows.map((r) => `<tr><th>${esc(r.label)}</th>${r.values.map((v, i) =>
      `<td class="${i === r.best_index ? "best" : ""}">${esc(v)}</td>`).join("")}</tr>`).join("");
    const el = h("div", { class: "comp" }, `<h3>Side by side</h3><div class="table-wrap"><table class="compare"><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`);
    const btns = h("div", { class: "choices" });
    c.models.forEach((m) => btns.append(h("button", {
      class: "btn secondary small", onclick: () => act({ type: "select_model", model_id: m.model_id }, `Configure the ${m.name}`),
    }, `Configure ${esc(m.name.replace("BMW ", ""))}`)));
    el.append(btns);
    return el;
  },

  tradeoffs(c) {
    const el = h("div", { class: "comp tradeoffs" }, `<h3>${esc(c.title)}</h3>`);
    c.items.forEach((t) => {
      const model = (t.description.match(/^(BMW [^(]+?) would fit/) || [])[1] || "";
      const row = h("div", { class: "tradeoff", title: t.description },
        `<span>${esc(t.label)}${model ? ` <span class="muted">→ ${esc(model.replace(/^BMW /, ""))}</span>` : ""}</span>`);
      row.append(h("button", {
        class: "text-link",
        onclick: () => { markDone(el); act({ type: "apply_tradeoff", patch: t.patch, label: t.label }, `Accept: ${t.label}`); },
      }, "Accept"));
      el.append(row);
    });
    return el;
  },

  option_toggles(c) {
    const el = h("div", { class: "comp" }, `<h3>${esc(c.title)}</h3>`);
    c.options.slice(0, 4).forEach((o) => el.append(optionRow(o, true)));
    if (c.options.length > 4) el.append(h("p", { class: "muted small-note" }, "More options in your configuration on the right."));
    return el;
  },

  conflict(c) {
    const el = h("div", { class: "comp conflict" }, `<p><strong>This combination isn't possible.</strong> ${esc(c.message)}</p>`);
    const row = h("div", { class: "choices" });
    c.resolutions.forEach((r) => row.append(h("button", {
      class: r.change ? "btn primary small" : "btn secondary small",
      onclick: () => {
        markDone(el);
        if (r.change) act({ type: "change_option", op: r.change.action, option_id: r.change.option_id, force: r.change.force }, r.label);
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
      `<tr><td>${esc(l.name)}<div class="why">${esc(l.reason)}</div></td><td class="num">${l.price ? eur(l.price) : "incl."}</td></tr>`).join("");
    const budget = c.budget.max != null
      ? `<p class="check ${c.budget.over_by ? "bad" : "good"}">${c.budget.over_by ? `${eur(c.budget.over_by)} over` : `${eur(c.budget.remaining)} under`} your ${eur(c.budget.max)} budget</p>` : "";
    const unmet = c.unmet_requirements.length
      ? `<ul class="violations">${c.unmet_requirements.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>`
      : `<p class="check good">✓ Meets all your needs: ${c.requirements.map(esc).join(" · ")}</p>`;
    const s = c.specs;
    const facts = [POWERTRAIN[s.powertrain], s.electric_range_km ? `${s.electric_range_km} km electric range` : `${s.total_range_km.toLocaleString("en-US")} km range`,
      `${s.seats} seats`, `${s.trunk_l} l boot`, s.tow_kg ? `tows ${s.tow_kg.toLocaleString("en-US")} kg` : ""].filter(Boolean);
    return h("div", { class: "comp summary" }, `
      <div class="summary-head"><div><p class="eyebrow">Your configuration</p><h3>${esc(c.model_name)}</h3></div>
        <span class="tag ${c.valid ? "dark" : "outline"}">${c.valid ? "Valid configuration" : "Needs attention"}</span></div>
      <div class="car">${carVisual(c.model_id, s.body, c.model_name)}</div>
      <div class="facts">${facts.map((f) => `<span>${esc(f)}</span>`).join("")}</div>
      <table class="lines"><tr><td>Base price</td><td class="num">${eur(c.base_price)}</td></tr>${lines}
        <tr class="total"><td>Total price</td><td class="num">${eur(c.total_price)}</td></tr></table>
      ${budget}${unmet}
      ${c.assumptions.length ? `<details><summary>Assumptions</summary><ul>${c.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""}`);
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
    act({ type: "change_option", op: wasOn ? "remove" : "add", option_id: o.id }, `${wasOn ? "Remove" : "Add"} ${o.name}`);
  });
  const detail = o.state === "unavailable" ? o.note
    : o.state === "included" || o.state === "standard" ? o.note
    : "";
  const rec = o.recommended && !compact ? `<span class="tag rec">Suggested</span>` : "";
  row.append(box, h("span", { class: "opt-name" }, `${esc(o.name)}${rec}${detail ? `<small>${esc(detail)}</small>` : ""}`),
    h("span", { class: "opt-price" }, o.state === "included" || o.state === "standard" ? "incl." : eur(o.price)));
  return row;
}

// ------------------------------------------------------------------ side panel

function renderState(state) {
  // needs
  els.needs.innerHTML = "";
  if (!state.requirements.length) els.needs.innerHTML = `<p class="muted">Nothing yet. Describe your situation in the chat.</p>`;
  state.requirements.forEach((r) => {
    const chip = h("span", { class: "chip" }, esc(r.label));
    chip.append(h("button", {
      class: "x", title: "Remove this requirement", "aria-label": `Remove ${r.label}`,
      onclick: () => act({ type: "remove_requirement", field: r.field }, `Remove requirement: ${r.label}`),
    }, "×"));
    els.needs.append(chip);
  });
  els.assumptionsBox.hidden = !state.assumptions.length;
  els.assumptions.innerHTML = state.assumptions.map((a) => `<li>${esc(a)}</li>`).join("");

  // configuration
  const v = state.configuration;
  if (!v) { els.config.innerHTML = `<p class="muted">Choose a model to start configuring.</p>`; return; }
  const b = v.budget;
  const pct = b.max ? Math.min(100, Math.round((v.total_price / b.max) * 100)) : 0;
  const openCats = new Set([...els.config.querySelectorAll("details.opt-group[open]")].map((d) => d.dataset.cat));
  const sp = v.specs;
  const status = v.valid ? (v.unmet_requirements.length ? ["outline", "Misses a need"] : ["dark", "Valid"]) : ["outline", "Invalid"];
  els.config.innerHTML = `
    <div class="config-model">
      <p class="kicker">${esc(BODY[sp.body] || sp.body)} · ${esc(POWERTRAIN[sp.powertrain])} · <span class="status ${status[0] === "dark" ? "ok" : "warn"}">${status[1]}</span></p>
      <h3>${esc(v.model_name)}</h3>
      <div class="car">${carVisual(v.model_id, sp.body, v.model_name)}</div>
      <div class="config-price"><span>Total price</span><strong>${eur(v.total_price)}</strong></div>
      ${b.max ? `<div class="budget-bar ${b.over_by ? "over" : ""}"><div></div></div>
        <div class="budget-note ${b.over_by ? "over" : ""}">${b.over_by ? `${eur(b.over_by)} over your budget` : `${eur(b.remaining)} left of your ${eur(b.max)} budget`}</div>` : ""}
      <div class="spec-grid">
        <div><span>${sp.powertrain === "bev" ? "Electric range" : "Total range"}</span><b>${(sp.powertrain === "bev" ? sp.electric_range_km : sp.total_range_km).toLocaleString("en-US")} km</b></div>
        <div><span>0–100 km/h</span><b>${sp.acceleration_s} s</b></div>
        <div><span>Seats</span><b>${sp.seats}</b></div>
        <div><span>Boot</span><b>${sp.trunk_l} l</b></div>
      </div>
      ${v.unmet_requirements.length ? `<ul class="violations">${v.unmet_requirements.map((u) => `<li>${esc(u.message)}</li>`).join("")}</ul>` : ""}
    </div>`;

  const fill = els.config.querySelector(".budget-bar div");
  if (fill) fill.style.width = `${pct}%`; // set via CSSOM: the CSP forbids inline style attributes

  // keep option toggles shown inside the chat in sync with the authoritative configuration
  const byId = Object.fromEntries(v.catalog_options.map((o) => [o.id, o]));
  els.messages.querySelectorAll("input[data-opt]").forEach((box) => {
    const o = byId[box.dataset.opt];
    if (o) box.checked = ["selected", "included", "standard"].includes(o.state);
  });

  const groups = {};
  v.catalog_options.forEach((o) => { (groups[o.category] ||= []).push(o); });
  for (const [cat, opts] of Object.entries(groups)) {
    const chosen = opts.filter((o) => o.state === "selected" || o.state === "included").length;
    const box = h("details", { class: "opt-group", "data-cat": cat, open: openCats.has(cat) || undefined },
      `<summary>${esc(cat)}${chosen ? `<span class="count">${chosen} selected</span>` : ""}</summary>`);
    opts.forEach((o) => box.append(optionRow(o)));
    els.config.append(box);
  }
  els.config.append(h("button", { class: "btn primary full", onclick: () => act({ type: "request_summary" }, "Show summary") }, "Review summary"));
}

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
els.newSession.addEventListener("click", () => { if (!busy) startSession().catch((e) => renderError(e.message)); });

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
loadBrandAssets().finally(() => restoreSession().catch((e) => renderError(`Could not reach the configurator service: ${e.message}`, () => location.reload())));
