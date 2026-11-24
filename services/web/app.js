// Configurator Assistant - web client.
// Renders the agent's messages and adaptive UI components; every user interaction is sent
// back to the agent service as either a free-text message or a structured action.

const API = "/api";
const $ = (sel) => document.querySelector(sel);
const els = {
  messages: $("#messages"), form: $("#composer"), input: $("#input"), send: $("#send"),
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
    body.transcript.forEach((m, i) => renderMessage(m, i < body.transcript.length - 1));
    renderState(body.state);
  } catch {
    await startSession();
  }
}

function setMode(mode) {
  els.mode.textContent = mode === "claude" ? "AI agent (Claude)" : "Guided mode (offline)";
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

function renderMessage(msg, historical = false) {
  const wrap = h("div", { class: `msg ${msg.role}` });
  if (msg.text) wrap.append(h("div", { class: "bubble" }, md(msg.text)));
  for (const c of msg.components || []) {
    const el = renderComponent(c);
    if (!el) continue;
    if (historical && ["question", "slider", "conflict", "tradeoffs"].includes(c.type)) el.classList.add("done");
    wrap.append(el);
  }
  els.messages.append(wrap);
  scroll();
}

const scroll = () => requestAnimationFrame(() => { els.messages.scrollTop = els.messages.scrollHeight; });

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
      class: "chip-btn",
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
      class: "primary small",
      onclick: () => { markDone(el); act({ type: "set_preference", key: c.preference, value: input.value / 100 }, `Preference: ${input.value}% sporty`); },
    }, "Apply");
    el.append(row, apply);
    return el;
  },

  model_cards(c) {
    const el = h("div", { class: "comp" }, `<h3>${esc(c.title)}</h3>`);
    const grid = h("div", { class: "cards" });
    c.cards.forEach((card) => {
      const fit = card.fits ? `<span class="badge ok">Meets your needs</span>` : `<span class="badge warn">Needs a compromise</span>`;
      const item = h("article", { class: "model-card" }, `
        <div class="model-top"><span class="pt">${esc(card.powertrain)}</span>${fit}</div>
        <h4>${esc(card.name)}</h4>
        <div class="price">from ${eur(card.entry_price)}${card.entry_price !== card.base_price ? ` <small>(base ${eur(card.base_price)} + needed options)</small>` : ""}</div>
        <div class="highlights">${card.highlights.map(esc).join(" · ")}</div>
        <ul class="reasons">${card.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
        ${card.violations.length ? `<ul class="violations">${card.violations.map((v) => `<li>${esc(v)}</li>`).join("")}</ul>` : ""}`);
      item.append(h("button", {
        class: card.fits ? "primary" : "secondary",
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
      class: "chip-btn", onclick: () => act({ type: "select_model", model_id: m.model_id }, `Configure the ${m.name}`),
    }, `Configure ${esc(m.name.replace("BMW ", ""))}`)));
    el.append(btns);
    return el;
  },

  tradeoffs(c) {
    const el = h("div", { class: "comp tradeoffs" }, `<h3>${esc(c.title)}</h3>`);
    c.items.forEach((t) => {
      const row = h("div", { class: "tradeoff" }, `<div><strong>${esc(t.label)}</strong><p>${esc(t.description)}</p></div>`);
      row.append(h("button", {
        class: "secondary small",
        onclick: () => { markDone(el); act({ type: "apply_tradeoff", patch: t.patch, label: t.label }, `Accept: ${t.label}`); },
      }, "Accept"));
      el.append(row);
    });
    return el;
  },

  option_toggles(c) {
    const el = h("div", { class: "comp" }, `<h3>${esc(c.title)}</h3>`);
    c.options.forEach((o) => el.append(optionRow(o, true)));
    return el;
  },

  conflict(c) {
    const el = h("div", { class: "comp conflict" }, `<p><strong>Conflict:</strong> ${esc(c.message)}</p>`);
    const row = h("div", { class: "choices" });
    c.resolutions.forEach((r) => row.append(h("button", {
      class: r.change ? "primary small" : "secondary small",
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
      ? `<p class="${c.budget.over_by ? "bad" : "good"}">${c.budget.over_by ? `${eur(c.budget.over_by)} over` : `${eur(c.budget.remaining)} under`} your ${eur(c.budget.max)} budget</p>` : "";
    const unmet = c.unmet_requirements.length
      ? `<ul class="violations">${c.unmet_requirements.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>`
      : `<p class="good">✓ Meets all stated needs: ${c.requirements.map(esc).join(" · ")}</p>`;
    const s = c.specs;
    return h("div", { class: "comp summary" }, `
      <h3>${esc(c.model_name)} <span class="badge ${c.valid ? "ok" : "warn"}">${c.valid ? "Valid configuration" : "Needs attention"}</span></h3>
      <p class="highlights">${esc(c.powertrain_label.charAt(0).toUpperCase() + c.powertrain_label.slice(1))} · ${s.electric_range_km ? s.electric_range_km + " km electric range · " : ""}${s.seats} seats · ${s.trunk_l} l boot${s.tow_kg ? " · tows " + s.tow_kg.toLocaleString("en-US") + " kg" : ""}</p>
      <table class="lines"><tr><td>Base price</td><td class="num">${eur(c.base_price)}</td></tr>${lines}
        <tr class="total"><td>Total</td><td class="num">${eur(c.total_price)}</td></tr></table>
      ${budget}${unmet}
      ${c.assumptions.length ? `<details><summary>Assumptions</summary><ul>${c.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""}`);
  },
};

// ------------------------------------------------------------------ option rows (chat + panel)

function optionRow(o, compact = false) {
  const locked = o.state === "standard" || o.state === "included";
  const on = o.state === "selected" || locked;
  const row = h("label", { class: `opt ${o.state}${o.recommended ? " rec" : ""}`, title: o.note || o.description });
  const box = h("input", { type: "checkbox", checked: on, disabled: locked, "data-opt": o.id });
  box.addEventListener("change", () => {
    const wasOn = !box.checked;
    box.checked = wasOn; // the server is the source of truth; state is re-synced from the response
    act({ type: "change_option", op: wasOn ? "remove" : "add", option_id: o.id }, `${wasOn ? "Remove" : "Add"} ${o.name}`);
  });
  const detail = o.state === "unavailable" ? o.note
    : o.state === "included" || o.state === "standard" ? o.note
    : compact && o.recommended_reason ? o.recommended_reason : "";
  row.append(box, h("span", { class: "opt-name" }, `${esc(o.name)}${detail ? `<small>${esc(detail)}</small>` : ""}`),
    h("span", { class: "opt-price" }, o.state === "included" || o.state === "standard" ? "incl." : eur(o.price)));
  return row;
}

// ------------------------------------------------------------------ side panel

function renderState(state) {
  // needs
  els.needs.innerHTML = "";
  if (!state.requirements.length) els.needs.innerHTML = `<p class="muted">Nothing yet - describe your situation in the chat.</p>`;
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
  if (!v) { els.config.innerHTML = `<p class="muted">Pick a model to start configuring.</p>`; return; }
  const b = v.budget;
  const pct = b.max ? Math.min(100, Math.round((v.total_price / b.max) * 100)) : 0;
  els.config.innerHTML = `
    <div class="config-head"><strong>${esc(v.model_name)}</strong><span class="badge ${v.valid && !v.unmet_requirements.length ? "ok" : "warn"}">${v.valid ? (v.unmet_requirements.length ? "Valid, misses a need" : "Valid") : "Invalid"}</span></div>
    <div class="total">${eur(v.total_price)}</div>
    ${b.max ? `<div class="budget-bar ${b.over_by ? "over" : ""}"><div></div></div>
      <div class="muted small">${b.over_by ? `${eur(b.over_by)} over budget` : `${eur(b.remaining)} left of ${eur(b.max)}`}</div>` : ""}
    <div class="specs">${[
      POWERTRAIN[v.specs.powertrain],
      v.specs.electric_range_km ? `${v.specs.electric_range_km} km electric` : `${v.specs.total_range_km.toLocaleString("en-US")} km range`,
      `${v.specs.seats} seats`, `${v.specs.trunk_l} l`,
    ].map((s) => `<span>${esc(s)}</span>`).join("")}</div>
    ${v.unmet_requirements.length ? `<ul class="violations">${v.unmet_requirements.map((u) => `<li>${esc(u.message)}</li>`).join("")}</ul>` : ""}`;

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
    const box = h("details", { class: "opt-group", open: opts.some((o) => o.state === "selected" || o.recommended) || undefined },
      `<summary>${esc(cat)}</summary>`);
    opts.forEach((o) => box.append(optionRow(o)));
    els.config.append(box);
  }
  els.config.append(h("button", { class: "primary full", onclick: () => act({ type: "request_summary" }, "Show summary") }, "Review summary"));
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

restoreSession().catch((e) => renderError(`Could not reach the configurator service: ${e.message}`, () => location.reload()));
