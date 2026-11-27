// Configurator Assistant - content script for the BMW configurator (configure.bmw.de).
// Adds an "AI mode" switch; switching it on reveals the configurator assistant app in an overlay
// (iframe) with a circular reveal from the switch, like a dark-mode transition.
// Everything lives in a closed shadow root so the page's styles and ours cannot interfere.

(() => {
  if (window.__configuratorAssistant) return; // injected once per page
  window.__configuratorAssistant = true;

  const DEFAULT_URL = "http://localhost:8080";

  const getAppUrl = () => new Promise((resolve) => {
    try {
      chrome.storage.sync.get({ appUrl: DEFAULT_URL }, (v) => resolve((v && v.appUrl) || DEFAULT_URL));
    } catch {
      resolve(DEFAULT_URL); // storage unavailable (e.g. when run outside the extension for testing)
    }
  });

  // Animatable angle for the glow ring (@property is ignored inside shadow roots, so register it here).
  try { CSS.registerProperty({ name: "--ca-angle", syntax: "<angle>", inherits: false, initialValue: "0deg" }); } catch { /* already registered */ }

  const host = document.createElement("div");
  host.id = "configurator-assistant-root";
  const root = host.attachShadow({ mode: "closed" });

  root.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; font-family: "bmwTypeNextWeb", "Helvetica Neue", Arial, sans-serif; }

      /* ---------- the AI mode switch: an "island" next to the configurator's navigation bar.
         Position (left/top/height) is set by placeSwitch() from the bar's live position. */
      .switch { position: fixed; left: 24px; top: 168px; height: 46px; z-index: 2147483647; display: inline-flex; align-items: center; gap: 6px;
        padding: 0 4px 0 12px; border: 0; border-radius: 999px; cursor: pointer; color: #262626; background: #fff;
        box-shadow: 0 4px 16px rgba(0,0,0,.12), inset 0 0 0 1px rgba(0,0,0,.06);
        transition: color .35s, background .35s, box-shadow .35s, opacity .2s; isolation: isolate; opacity: 0; }
      .switch.placed { opacity: 1; }
      .switch:focus-visible { outline: 2px solid #1c69d4; outline-offset: 3px; }
      .switch.docked { opacity: 0; visibility: hidden; pointer-events: none; transition: opacity .25s .35s, visibility 0s .6s; }
      /* animated glow ring when on */
      .switch::before { content: ""; position: absolute; inset: -2px; z-index: -1; border-radius: inherit; padding: 2px; opacity: 0;
        background: conic-gradient(from var(--ca-angle, 0deg), #1c69d4, #7aa8ff, #b38bff, #1c69d4);
        -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude;
        transition: opacity .35s; animation: spin 3s linear infinite; }
      .switch[aria-checked="true"] { color: #fff; background: linear-gradient(135deg, #0b2a5b 0%, #1c69d4 100%);
        box-shadow: 0 6px 24px rgba(28,105,212,.45), 0 0 0 1px rgba(255,255,255,.08) inset; }
      .switch[aria-checked="true"]::before { opacity: 1; }
      @keyframes spin { to { --ca-angle: 360deg; } }

      .label { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.1; text-align: left; white-space: nowrap; }
      .label b { font-size: 15px; font-weight: 500; letter-spacing: .01em; }
      .label small { font-size: 11px; opacity: .65; }
      /* compact (beside the navigation bar): "✦ AI" + toggle; the full label shows only where there is room */
      .switch.compact .long, .switch.compact small { display: none; }
      .spark { width: 15px; height: 15px; flex: none; transition: transform .6s cubic-bezier(.4,0,.2,1); }
      .switch[aria-checked="true"] .spark { transform: rotate(180deg) scale(1.1); }

      /* ---------- idle "waiting to be switched on": twinkling icon, shimmer sweep, flying sparks */
      .switch[aria-checked="false"] .spark { color: #1c69d4; animation: twinkle 2.4s ease-in-out infinite; }
      @keyframes twinkle {
        0%, 100% { transform: scale(1) rotate(0deg); filter: drop-shadow(0 0 0 rgba(28,105,212,0)); }
        45% { transform: scale(1.28) rotate(18deg); filter: drop-shadow(0 0 5px rgba(28,105,212,.75)); }
        60% { transform: scale(.92) rotate(10deg); }
      }
      .switch::after { content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; opacity: 0;
        background: linear-gradient(105deg, transparent 35%, rgba(122,168,255,.35) 48%, rgba(179,139,255,.25) 52%, transparent 65%) no-repeat;
        background-size: 250% 100%; }
      .switch[aria-checked="false"]::after { opacity: 1; animation: shimmer 3.6s ease-in-out infinite; }
      @keyframes shimmer { 0%, 55% { background-position: 130% 0; } 100% { background-position: -130% 0; } }
      .sparks { position: absolute; inset: 0; pointer-events: none; overflow: visible; }
      .sparks i { position: absolute; left: 0; top: 0; width: 5px; height: 5px; border-radius: 50%; will-change: transform, opacity; }
      .sparks i.star { width: 9px; height: 9px; border-radius: 0;
        clip-path: polygon(50% 0, 61% 39%, 100% 50%, 61% 61%, 50% 100%, 39% 61%, 0 50%, 39% 39%); }

      .track { position: relative; width: 40px; height: 24px; margin-left: 2px; flex: none; border-radius: 12px; background: #d9d9d9; transition: background .35s; }
      .switch[aria-checked="true"] .track { background: rgba(255,255,255,.22); }
      .knob { position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: #fff;
        display: flex; align-items: center; justify-content: center; color: #1c69d4;
        box-shadow: 0 2px 5px rgba(0,0,0,.25); transition: transform .4s cubic-bezier(.5,1.6,.4,1); }
      .switch[aria-checked="true"] .knob { transform: translateX(16px); }
      .knob svg { width: 10px; height: 10px; opacity: 0; transform: scale(.4); transition: opacity .3s, transform .3s; }
      .switch[aria-checked="true"] .knob svg { opacity: 1; transform: none; }

      /* ---------- the overlay: circular reveal from the switch */
      .backdrop { position: fixed; inset: 0; z-index: 2147483646; display: flex; align-items: center; justify-content: center;
        background: radial-gradient(circle at var(--x) var(--y), rgba(11,42,91,.72), rgba(10,14,22,.78));
        backdrop-filter: blur(4px); clip-path: circle(0 at var(--x) var(--y)); visibility: hidden;
        transition: clip-path .65s cubic-bezier(.4,0,.2,1), visibility 0s .65s; }
      .backdrop.open { clip-path: circle(150% at var(--x) var(--y)); visibility: visible; transition: clip-path .7s cubic-bezier(.4,0,.2,1); }
      .panel { width: min(1440px, 94vw); height: min(920px, 90vh); display: flex; flex-direction: column; background: #fff;
        box-shadow: 0 24px 80px rgba(0,0,0,.4); opacity: 0; transform: translateY(18px) scale(.98);
        transition: opacity .3s ease, transform .35s cubic-bezier(.4,0,.2,1); }
      .backdrop.open .panel { opacity: 1; transform: none; transition-delay: .25s; }
      .bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 8px 0 20px; height: 44px;
        border-bottom: 1px solid #e6e6e6; color: #262626; font-size: 13px; }
      .bar .title { display: flex; align-items: center; gap: 8px; }
      .bar .title svg { width: 16px; height: 16px; color: #1c69d4; }
      .bar .tag { font-size: 11px; color: #666; border: 1px solid #ddd; border-radius: 10px; padding: 1px 8px; }
      .bar .actions { display: flex; align-items: center; gap: 4px; }
      .bar a, .bar button { display: inline-flex; align-items: center; justify-content: center; height: 32px; padding: 0 10px; border: 0;
        background: none; color: #262626; font-size: 13px; text-decoration: none; cursor: pointer; border-radius: 3px; }
      .bar a:hover, .bar button:hover { background: #f2f2f2; }
      /* compact AI mode switch in the overlay's title bar (always "on" while the overlay is open) */
      .bar .mini { gap: 8px; height: 30px; padding: 0 4px 0 10px; border-radius: 15px; color: #fff; font-size: 12px; font-weight: 500;
        background: linear-gradient(135deg, #0b2a5b, #1c69d4); box-shadow: 0 2px 10px rgba(28,105,212,.35); }
      .bar .mini:hover { background: linear-gradient(135deg, #0b2a5b, #0653b6); }
      .bar .mini:focus-visible { outline: 2px solid #1c69d4; outline-offset: 2px; }
      .bar .mini svg { width: 13px; height: 13px; }
      .bar .mini .t { position: relative; width: 34px; height: 22px; border-radius: 11px; background: rgba(255,255,255,.25); }
      .bar .mini .k { position: absolute; top: 3px; left: 15px; width: 16px; height: 16px; border-radius: 50%; background: #fff; }
      iframe { flex: 1; width: 100%; border: 0; background: #fff; }

      @media (max-width: 700px) { .panel { width: 100vw; height: 100vh; } }
      @media (prefers-reduced-motion: reduce) {
        .switch::before, .switch::after, .switch .spark { animation: none !important; }
        .sparks { display: none; }
        .backdrop, .backdrop.open, .panel, .knob, .spark { transition-duration: .01s !important; transition-delay: 0s !important; }
      }
    </style>

    <button class="switch compact" type="button" role="switch" aria-checked="false" aria-label="AI mode" title="AI mode">
      <svg class="spark" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
        <path d="M12 2l1.8 5.6L19.5 9.5l-5.7 1.9L12 17l-1.8-5.6L4.5 9.5l5.7-1.9z"/>
        <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" opacity=".7"/>
      </svg>
      <span class="label"><b>AI<span class="long"> mode</span></b><small class="state">Off</small></span>
      <span class="track" aria-hidden="true"><span class="knob">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.8 5.6L19.5 9.5l-5.7 1.9L12 17l-1.8-5.6L4.5 9.5l5.7-1.9z"/></svg>
      </span></span>
      <span class="sparks" aria-hidden="true"></span>
    </button>

    <div class="backdrop" role="dialog" aria-modal="true" aria-label="Configurator Assistant">
      <div class="panel">
        <div class="bar">
          <span class="title">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l1.8 5.6L19.5 9.5l-5.7 1.9L12 17l-1.8-5.6L4.5 9.5l5.7-1.9z"/></svg>
            Configurator Assistant <span class="tag">Prototype</span>
          </span>
          <span class="actions">
            <a class="newtab" target="_blank" rel="noopener">Open in new tab ↗</a>
            <button class="mini" type="button" role="switch" aria-checked="true" aria-label="AI mode (switch off to close)">
              <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l1.8 5.6L19.5 9.5l-5.7 1.9L12 17l-1.8-5.6L4.5 9.5l5.7-1.9z"/></svg>
              AI mode <span class="t" aria-hidden="true"><span class="k"></span></span>
            </button>
          </span>
        </div>
      </div>
    </div>`;

  const sw = root.querySelector(".switch");
  const state = root.querySelector(".state");
  const backdrop = root.querySelector(".backdrop");
  const panel = root.querySelector(".panel");
  const newTab = root.querySelector(".newtab");
  const mini = root.querySelector(".mini");
  let frame = null;
  let previousOverflow = "";

  // ---- placement: next to the configurator's navigation bar ("island" tab bar)
  // BMW renders it as <con-island-navigation id="menu-tabs"> inside web components, so search shadow roots too.
  let nav = null;
  function findNav() {
    const stack = [document];
    while (stack.length) {
      const scope = stack.pop();
      const hit = scope.querySelector("con-island-navigation, #menu-tabs");
      if (hit) return hit;
      for (const el of scope.querySelectorAll("*")) if (el.shadowRoot) stack.push(el.shadowRoot);
    }
    return null;
  }

  function placeSwitch() {
    if (!nav || !nav.isConnected) nav = findNav();
    const r = nav && nav.getBoundingClientRect();
    if (r && r.width > 0 && r.height > 0) {
      const gap = 8;
      sw.style.height = `${Math.round(r.height)}px`;
      // full label if there is room to the right of the bar, otherwise compact "✦ AI"
      sw.classList.remove("compact");
      if (innerWidth - r.right < sw.offsetWidth + gap * 2) sw.classList.add("compact");
      if (innerWidth - r.right >= sw.offsetWidth + gap * 2) {
        sw.style.left = `${Math.round(r.right + gap)}px`;              // beside the bar, same height
        sw.style.top = `${Math.round(r.top)}px`;
      } else {
        sw.style.left = `${Math.round(r.left)}px`;                     // no room: just below the bar's start
        sw.style.top = `${Math.round(r.bottom + 10)}px`;
      }
    } else {
      // Bar not found or hidden (phone layout): top left, above the vehicle image on phones.
      const small = innerWidth < 700;
      sw.classList.add("compact");
      sw.style.height = small ? "40px" : "46px";
      sw.style.left = small ? "12px" : "24px";
      sw.style.top = small ? "12px" : "168px";
    }
    sw.classList.add("placed");
  }

  // ---- flying sparks while AI mode is off ("waiting to be switched on")
  const sparks = root.querySelector(".sparks");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const COLORS = ["#1c69d4", "#3d86ff", "#7aa8ff", "#b38bff", "#ffd36e"];

  function emitSpark(fromIcon = false) {
    const w = sw.offsetWidth, h = sw.offsetHeight;
    // start on the pill's outline (mostly around the ✦ icon), fly outwards
    let x, y, angle;
    if (fromIcon || Math.random() < 0.45) {
      x = 18 + Math.random() * 6; y = h / 2 + (Math.random() - 0.5) * 8;
      angle = Math.PI + (Math.random() - 0.5) * Math.PI * 1.4;        // left, up and down
    } else {
      const top = Math.random() < 0.5;
      x = 10 + Math.random() * (w - 20); y = top ? 2 : h - 2;
      angle = (top ? -Math.PI / 2 : Math.PI / 2) + (Math.random() - 0.5) * 1.2;
    }
    const dist = 16 + Math.random() * 26;
    const dx = Math.cos(angle) * dist, dy = Math.sin(angle) * dist;
    const el = document.createElement("i");
    const star = Math.random() < 0.4;
    if (star) el.className = "star";
    const color = COLORS[Math.floor(Math.random() * COLORS.length)];
    el.style.background = color;
    if (!star) el.style.boxShadow = `0 0 6px 1px ${color}`;
    sparks.append(el);
    const spin = (Math.random() - 0.5) * 360;
    const anim = el.animate([
      { transform: `translate(${x}px, ${y}px) scale(.3) rotate(0deg)`, opacity: 0 },
      { transform: `translate(${x + dx * .35}px, ${y + dy * .35}px) scale(1) rotate(${spin * .4}deg)`, opacity: 1, offset: .25 },
      { transform: `translate(${x + dx}px, ${y + dy + 6}px) scale(.2) rotate(${spin}deg)`, opacity: 0 },  // slight drop at the end
    ], { duration: 900 + Math.random() * 700, easing: "cubic-bezier(.2,.7,.4,1)" });
    anim.onfinish = () => el.remove();
  }

  let sparkTick = 0;
  setInterval(() => {
    if (isOn() || reducedMotion.matches || document.hidden || !sw.classList.contains("placed")) return;
    sparkTick++;
    emitSpark();
    if (Math.random() < 0.35) emitSpark();
    if (sparkTick % 16 === 0) for (let i = 0; i < 6; i++) setTimeout(() => emitSpark(true), i * 40);  // small burst now and then
  }, 260);

  // The reveal grows out of the switch's knob.
  function setOrigin() {
    const r = root.querySelector(".knob").getBoundingClientRect();
    backdrop.style.setProperty("--x", `${r.left + r.width / 2}px`);
    backdrop.style.setProperty("--y", `${r.top + r.height / 2}px`);
  }

  async function turnOn() {
    setOrigin();
    sw.setAttribute("aria-checked", "true");
    state.textContent = "On";
    const appUrl = await getAppUrl();
    newTab.href = appUrl;
    if (!frame || frame.dataset.src !== appUrl) {
      // Created once and kept while AI mode is off, so the conversation survives.
      frame?.remove();
      frame = document.createElement("iframe");
      frame.title = "Configurator Assistant";
      frame.dataset.src = appUrl;
      // Cross-site frames get the microphone only when allowed here (for the app's voice mode).
      // Chrome then asks the visitor once, on behalf of this site. Set before src, it applies on load.
      frame.allow = "clipboard-write; microphone";
      frame.src = appUrl;
      panel.append(frame);
    }
    previousOverflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = "hidden"; // no scrolling of the configurator behind the overlay
    backdrop.classList.add("open");
    sw.classList.add("docked"); // hands over to the compact switch in the overlay's title bar
    setTimeout(() => { if (isOn()) mini.focus(); }, 650);
  }

  function turnOff() {
    setOrigin();
    sw.setAttribute("aria-checked", "false");
    state.textContent = "Off";
    sw.classList.remove("docked");
    backdrop.classList.remove("open");
    document.documentElement.style.overflow = previousOverflow;
    sw.focus();
  }

  const isOn = () => sw.getAttribute("aria-checked") === "true";
  sw.addEventListener("click", () => (isOn() ? turnOff() : turnOn()));
  mini.addEventListener("click", turnOff);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) turnOff(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isOn()) turnOff(); });
  window.addEventListener("resize", () => { placeSwitch(); setOrigin(); });
  // The configurator is a single-page app: keep following the bar as it renders, moves or is replaced.
  setInterval(() => { if (!isOn()) placeSwitch(); }, 700);

  document.documentElement.append(host);
  placeSwitch();
})();
