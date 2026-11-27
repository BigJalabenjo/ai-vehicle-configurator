// UI language (English or German) for the web client.
// The choice is kept per browser; the agent is told about it, so replies, catalog texts and the
// voice (speech recognition and read-aloud) follow the same language.

export const LANGUAGES = ["en", "de"];
const KEY = "language";

let current = (() => {
  try {
    const saved = localStorage.getItem(KEY);
    if (LANGUAGES.includes(saved)) return saved;
  } catch { /* storage unavailable */ }
  return (navigator.language || "").toLowerCase().startsWith("de") ? "de" : "en";
})();

export const lang = () => current;
const locale = () => (current === "de" ? "de-DE" : "en-US");

export function setLang(code) {
  if (!LANGUAGES.includes(code)) return;
  current = code;
  try { localStorage.setItem(KEY, code); } catch { /* storage unavailable */ }
  applyStatic();
}

export const num = (v) => Number(v).toLocaleString(locale(), { maximumFractionDigits: 0 });
export const eur = (v) => (current === "de" ? `${num(v)} €` : `€${num(v)}`);

export function t(key, vars = {}) {
  const text = STRINGS[current][key] ?? STRINGS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
}

export const words = (key) => WORDS[current][key];

// Static markup: data-i18n sets the text, data-i18n-attr="attr:key,attr:key" sets attributes.
export function applyStatic(root = document) {
  document.documentElement.lang = current;
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-attr]").forEach((el) => {
    for (const pair of el.dataset.i18nAttr.split(",")) {
      const [attr, key] = pair.split(":");
      el.setAttribute(attr.trim(), t(key.trim()));
    }
  });
  const title = document.querySelector("title[data-i18n-title]");
  if (title) document.title = t(title.dataset.i18nTitle);
  document.querySelectorAll(".lang-switch button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === current)));
}

// EN | DE toggle; onChange runs after the language has switched.
export function mountSwitch(container, onChange = () => {}) {
  const group = document.createElement("div");
  group.className = "lang-switch";
  group.setAttribute("role", "group");
  group.dataset.i18nAttr = "aria-label:language";
  for (const code of LANGUAGES) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.lang = code;
    b.textContent = code.toUpperCase();
    b.setAttribute("lang", code);
    b.title = code === "de" ? "Deutsch" : "English";
    b.addEventListener("click", () => {
      if (code === current) return;
      setLang(code);
      onChange(code);
    });
    group.append(b);
  }
  container.prepend(group);
  applyStatic();
}

const WORDS = {
  en: {
    powertrain: { bev: "Electric", phev: "Plug-in hybrid", petrol: "Petrol", diesel: "Diesel" },
    body: { sav: "SAV", touring: "Touring", gran_coupe: "Gran Coupé", tourer: "Active Tourer", sedan: "Sedan" },
    fold: { model_cards: "suggested models", comparison: "comparison", option_toggles: "suggested options", summary: "summary" },
  },
  de: {
    powertrain: { bev: "Elektrisch", phev: "Plug-in-Hybrid", petrol: "Benziner", diesel: "Diesel" },
    body: { sav: "SAV", touring: "Touring", gran_coupe: "Gran Coupé", tourer: "Active Tourer", sedan: "Limousine" },
    fold: { model_cards: "Modellvorschläge", comparison: "Vergleich", option_toggles: "Optionsvorschläge", summary: "Zusammenfassung" },
  },
};

const STRINGS = {
  en: {
    // page
    page_title: "BMW Configurator Assistant",
    login_title: "Sign in · BMW Configurator Assistant",
    product: "Configurator Assistant",
    language: "Language",
    new_conversation: "New conversation",
    assistant: "Assistant",
    minimize: "Minimize the assistant",
    eyebrow: "AI Assistant · Prototype with a fictional catalog",
    hero: "Find and configure your BMW.",
    your_needs: "Your needs",
    how_interpreted: "How I interpreted this",
    placeholder: "Ask anything…",
    message: "Message",
    send: "Send",
    end_voice: "End voice",
    talk: "Talk hands-free",
    end_talk: "End hands-free voice",
    // errors and status
    sign_in_please: "Please sign in.",
    request_failed: "Request failed ({status})",
    voice_failed: "Voice request failed ({status})",
    session_expired: "Your session expired. Starting a new one…",
    retry: "Retry",
    unreachable: "Could not reach the configurator service: {error}",
    // chat components
    show_earlier: "Show earlier {what}",
    details: "details",
    comfort_vs_sporty: "Comfort versus sporty",
    preference_echo: "Preference: {pct}% sporty",
    apply: "Apply",
    meets_needs: "Meets your needs",
    needs_compromise: "Needs a compromise",
    from: "from",
    configure: "Configure",
    configure_the: "Configure the {name}",
    configure_short: "Configure {name}",
    side_by_side: "Side by side",
    accept: "Accept",
    accept_echo: "Accept: {label}",
    more_options: "More options in the configurator.",
    not_possible_inline: "This combination isn't possible: {message}",
    not_possible: "This combination isn't possible.",
    not_possible_title: "This combination isn't possible",
    conflict: "Conflict",
    incl: "incl.",
    over_budget_by: "{amount} over",
    under_budget_by: "{amount} under",
    your_budget: "your {amount} budget",
    meets_all: "✓ Meets all your needs: {list}",
    km_electric: "{km} km electric range",
    km_range: "{km} km range",
    seats_n: "{n} seats",
    boot_l: "{l} l boot",
    tows_kg: "tows {kg} kg",
    your_configuration: "Your configuration",
    valid: "Valid configuration",
    needs_attention: "Needs attention",
    base_price: "Base price",
    total_price: "Total price",
    assumptions: "Assumptions",
    suggested: "Suggested",
    // needs
    none_yet: "None yet",
    nothing_yet: "Nothing yet. Describe your situation in the chat.",
    remove_requirement: "Remove this requirement",
    remove_x: "Remove {label}",
    remove_echo: "Remove requirement: {label}",
    // stage
    valid_meets_all: "Valid configuration · meets all your needs",
    over_your_budget: "{amount} over your budget",
    left_of: "{amount} left of {max}",
    electric_range: "Electric range",
    total_range: "Total range",
    seats: "Seats",
    boot: "Boot",
    close: "Close",
    adjust: "Adjust",
    review_summary: "Review summary",
    show_summary: "Show summary",
    not_offered: "Not available on this model ({n})",
    // needs editor
    not_needed: "Not needed",
    bike_carrier: "Bike carrier",
    adjust_needs: "Adjust your needs",
    budget_up_to: "Budget up to (€)",
    no_limit: "No limit",
    powertrain: "Powertrain",
    powertrain_strictness: "Powertrain strictness",
    preferred: "preferred",
    required: "required",
    body_style: "Body style",
    seats_at_least: "Seats, at least",
    any: "Any",
    child_seats: "Child seats",
    none: "None",
    boot_at_least: "Boot, at least (l)",
    towing: "Towing",
    long_distance: "Regular long-distance trips",
    comfort_or_sport: "Comfort or sport",
    no_preference: "No preference",
    pct_sporty: "{pct}% sporty",
    comfort_to_sport: "Comfort to sport",
    cancel: "Cancel",
    // feedback
    needs_not_saved: "Those needs couldn't be saved.",
    needs_unmet: "Needs updated. This configuration doesn't meet: {list}",
    needs_ok: "Needs updated. This configuration still meets them.",
    change_impossible: "That change isn't possible.",
    updated: "Updated.",
    // voice
    v_starting: "Starting the microphone…",
    v_listening: "Listening…",
    v_thinking: "Thinking…",
    v_speaking: "Speaking · just talk to interrupt",
    mic_blocked: "Microphone access was blocked. Allow it in the browser to talk to the assistant.",
    mic_failed: "Couldn't start the microphone.",
    not_understood: "Couldn't understand that. Please try again.",
    play_failed: "Couldn't play the reply aloud.",
    // login
    login_eyebrow: "Prototype · access restricted",
    sign_in: "Sign in",
    login_hint: "Enter the access password to continue.",
    password: "Password",
    enter_password: "Please enter the password.",
    signing_in: "Signing in…",
    too_many: "Too many attempts. Please wait a minute and try again.",
    wrong_password: "Incorrect password. Please try again.",
    server_unreachable: "Could not reach the server. Please try again.",
  },
  de: {
    page_title: "BMW Konfigurator-Assistent",
    login_title: "Anmelden · BMW Konfigurator-Assistent",
    product: "Konfigurator-Assistent",
    language: "Sprache",
    new_conversation: "Neues Gespräch",
    assistant: "Assistent",
    minimize: "Assistent minimieren",
    eyebrow: "KI-Assistent · Prototyp mit fiktivem Katalog",
    hero: "Finden und konfigurieren Sie Ihren BMW.",
    your_needs: "Ihre Anforderungen",
    how_interpreted: "So habe ich das verstanden",
    placeholder: "Fragen Sie einfach…",
    message: "Nachricht",
    send: "Senden",
    end_voice: "Sprachmodus beenden",
    talk: "Freihändig sprechen",
    end_talk: "Freihändigen Sprachmodus beenden",
    sign_in_please: "Bitte melden Sie sich an.",
    request_failed: "Anfrage fehlgeschlagen ({status})",
    voice_failed: "Sprachanfrage fehlgeschlagen ({status})",
    session_expired: "Ihre Sitzung ist abgelaufen. Eine neue wird gestartet…",
    retry: "Erneut versuchen",
    unreachable: "Der Konfigurator-Dienst ist nicht erreichbar: {error}",
    show_earlier: "Frühere {what} anzeigen",
    details: "Details",
    comfort_vs_sporty: "Komfort oder sportlich",
    preference_echo: "Vorliebe: {pct} % sportlich",
    apply: "Übernehmen",
    meets_needs: "Erfüllt Ihre Anforderungen",
    needs_compromise: "Braucht einen Kompromiss",
    from: "ab",
    configure: "Konfigurieren",
    configure_the: "{name} konfigurieren",
    configure_short: "{name} konfigurieren",
    side_by_side: "Im Vergleich",
    accept: "Übernehmen",
    accept_echo: "Übernehmen: {label}",
    more_options: "Weitere Optionen im Konfigurator.",
    not_possible_inline: "Diese Kombination ist nicht möglich: {message}",
    not_possible: "Diese Kombination ist nicht möglich.",
    not_possible_title: "Diese Kombination ist nicht möglich",
    conflict: "Konflikt",
    incl: "inkl.",
    over_budget_by: "{amount} über",
    under_budget_by: "{amount} unter",
    your_budget: "Ihrem Budget von {amount}",
    meets_all: "✓ Erfüllt alle Ihre Anforderungen: {list}",
    km_electric: "{km} km elektrische Reichweite",
    km_range: "{km} km Reichweite",
    seats_n: "{n} Sitze",
    boot_l: "{l} l Kofferraum",
    tows_kg: "zieht {kg} kg",
    your_configuration: "Ihre Konfiguration",
    valid: "Gültige Konfiguration",
    needs_attention: "Braucht Aufmerksamkeit",
    base_price: "Grundpreis",
    total_price: "Gesamtpreis",
    assumptions: "Annahmen",
    suggested: "Empfohlen",
    none_yet: "Noch keine",
    nothing_yet: "Noch nichts. Beschreiben Sie Ihre Situation im Chat.",
    remove_requirement: "Anforderung entfernen",
    remove_x: "{label} entfernen",
    remove_echo: "Anforderung entfernen: {label}",
    valid_meets_all: "Gültige Konfiguration · erfüllt alle Ihre Anforderungen",
    over_your_budget: "{amount} über Ihrem Budget",
    left_of: "{amount} von {max} übrig",
    electric_range: "Elektrische Reichweite",
    total_range: "Gesamtreichweite",
    seats: "Sitze",
    boot: "Kofferraum",
    close: "Schließen",
    adjust: "Anpassen",
    review_summary: "Zusammenfassung ansehen",
    show_summary: "Zusammenfassung anzeigen",
    not_offered: "Für dieses Modell nicht erhältlich ({n})",
    not_needed: "Nicht nötig",
    bike_carrier: "Fahrradträger",
    adjust_needs: "Anforderungen anpassen",
    budget_up_to: "Budget bis (€)",
    no_limit: "Ohne Limit",
    powertrain: "Antrieb",
    powertrain_strictness: "Wie verbindlich ist der Antrieb",
    preferred: "bevorzugt",
    required: "verpflichtend",
    body_style: "Karosserie",
    seats_at_least: "Sitze, mindestens",
    any: "Egal",
    child_seats: "Kindersitze",
    none: "Keine",
    boot_at_least: "Kofferraum, mindestens (l)",
    towing: "Anhängelast",
    long_distance: "Regelmäßig Langstrecke",
    comfort_or_sport: "Komfort oder Sport",
    no_preference: "Keine Vorliebe",
    pct_sporty: "{pct} % sportlich",
    comfort_to_sport: "Komfort bis Sport",
    cancel: "Abbrechen",
    needs_not_saved: "Diese Anforderungen konnten nicht gespeichert werden.",
    needs_unmet: "Anforderungen aktualisiert. Diese Konfiguration erfüllt nicht: {list}",
    needs_ok: "Anforderungen aktualisiert. Diese Konfiguration erfüllt sie weiterhin.",
    change_impossible: "Diese Änderung ist nicht möglich.",
    updated: "Aktualisiert.",
    v_starting: "Mikrofon wird gestartet…",
    v_listening: "Ich höre zu…",
    v_thinking: "Einen Moment…",
    v_speaking: "Ich spreche · einfach reden, um zu unterbrechen",
    mic_blocked: "Der Mikrofonzugriff wurde blockiert. Erlauben Sie ihn im Browser, um mit dem Assistenten zu sprechen.",
    mic_failed: "Das Mikrofon konnte nicht gestartet werden.",
    not_understood: "Das habe ich nicht verstanden. Bitte versuchen Sie es noch einmal.",
    play_failed: "Die Antwort konnte nicht vorgelesen werden.",
    login_eyebrow: "Prototyp · eingeschränkter Zugang",
    sign_in: "Anmelden",
    login_hint: "Geben Sie das Zugangspasswort ein, um fortzufahren.",
    password: "Passwort",
    enter_password: "Bitte geben Sie das Passwort ein.",
    signing_in: "Anmeldung läuft…",
    too_many: "Zu viele Versuche. Bitte warten Sie eine Minute und versuchen Sie es erneut.",
    wrong_password: "Falsches Passwort. Bitte versuchen Sie es erneut.",
    server_unreachable: "Der Server ist nicht erreichbar. Bitte versuchen Sie es erneut.",
  },
};
