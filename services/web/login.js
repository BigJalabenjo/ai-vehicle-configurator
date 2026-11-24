// Sign-in page. The password is checked by the agent service, which sets an HTTP-only cookie.

const form = document.getElementById("login-form");
const input = document.getElementById("password");
const error = document.getElementById("login-error");
const submit = document.getElementById("login-submit");

// Already signed in (or protection disabled)? Go straight to the app.
fetch("/api/auth/status")
  .then((r) => r.json())
  .then((s) => { if (!s.enabled || s.authenticated) location.replace("/"); })
  .catch(() => {});

// Show the brand logo if one is installed (same asset manifest as the app).
fetch("assets/manifest.json")
  .then((r) => (r.ok ? r.json() : []))
  .then((files) => {
    loadFonts(files);
    const logo = files.find((f) => /^logo\.(svg|png|webp|jpe?g)$/i.test(f) || /^logo\./.test(f));
    if (!logo) return;
    const img = document.getElementById("logo");
    img.addEventListener("load", () => { img.hidden = false; document.body.classList.add("has-logo"); }, { once: true });
    img.src = `assets/${encodeURI(logo)}`;
  })
  .catch(() => {});

// Same brand font as the app (weights read from the file names), if installed.
function loadFonts(files) {
  const formats = { woff2: "woff2", woff: "woff", otf: "opentype", ttf: "truetype" };
  const weights = [[/thin|hairline/i, "100"], [/light/i, "300"], [/medium/i, "500"], [/bold/i, "700"], [/./, "400"]];
  const loads = files.filter((f) => f.startsWith("fonts/") && formats[f.split(".").pop().toLowerCase()]).map((f) => {
    const weight = weights.find(([re]) => re.test(f.split("/").pop()))[1];
    const ext = f.split(".").pop().toLowerCase();
    return new FontFace("BMW Brand", `url(assets/${encodeURI(f)}) format("${formats[ext]}")`, { weight }).load()
      .then((face) => { document.fonts.add(face); return true; }).catch(() => false);
  });
  Promise.all(loads).then((ok) => { if (ok.some(Boolean)) document.documentElement.classList.add("brand-font"); });
}

function showError(text) {
  error.textContent = text;
  error.hidden = false;
  input.setAttribute("aria-invalid", "true");
  input.select();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!input.value) { showError("Please enter the password."); return; }
  submit.disabled = true;
  submit.textContent = "Signing in…";
  error.hidden = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password: input.value }),
    });
    if (res.ok) { location.replace("/"); return; }
    if (res.status === 429 || res.status === 503) showError("Too many attempts. Please wait a minute and try again.");
    else showError("Incorrect password. Please try again.");
  } catch {
    showError("Could not reach the server. Please try again.");
  } finally {
    submit.disabled = false;
    submit.textContent = "Sign in";
  }
});
