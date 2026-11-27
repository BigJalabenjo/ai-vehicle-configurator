"""UI language (English or German) for everything the agent says itself.

The session's language is set for the duration of a request (``use``); the catalog client forwards it
to the catalog service, so rule messages and catalog texts come back in the same language. The LLM
is told the language in its state block and replies in it. Internal notes for the LLM stay English.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

Language = Literal["en", "de"]
LANGUAGES: tuple[Language, ...] = ("en", "de")
DEFAULT: Language = "en"
NAMES = {"en": "English", "de": "German"}

current: ContextVar[str] = ContextVar("lang", default=DEFAULT)


def lang() -> str:
    return current.get()


def use(code: str) -> None:
    current.set(code if code in LANGUAGES else DEFAULT)


def num(value: float) -> str:
    text = f"{value:,.0f}"
    return text.replace(",", ".") if lang() == "de" else text


def eur(value: float) -> str:
    return f"{num(value)} €" if lang() == "de" else f"€{num(value)}"


def t(key: str, **kw) -> str:
    return MESSAGES[lang()][key].format(**kw)


def words(key: str) -> dict[str, str]:
    """A label table (powertrains, body styles, ...) in the current language."""
    return LABELS[lang()][key]


def join_or(items: list[str]) -> str:
    return f" {t('or')} ".join(items)


LABELS: dict[str, dict[str, dict[str, str]]] = {
    "en": {
        "powertrain": {"bev": "electric", "phev": "plug-in hybrid", "petrol": "petrol", "diesel": "diesel"},
        "powertrain_short": {"bev": "Electric", "phev": "Plug-in hybrid", "petrol": "Petrol", "diesel": "Diesel"},
        "body": {"gran_coupe": "Gran Coupé", "touring": "estate (Touring)", "sav": "SUV (SAV)",
                 "tourer": "compact tourer", "sedan": "saloon"},
        "field": {"budget_max": "budget", "powertrain_preferred": "powertrain preference",
                  "powertrain_required": "powertrain requirement", "min_seats": "seats", "child_seats": "child seats",
                  "long_distance": "long-distance trips", "towing_kg": "towing", "min_trunk_l": "boot size",
                  "body_styles": "body style", "sportiness": "comfort vs. sport", "must_have_options": "must-have options"},
    },
    "de": {
        "powertrain": {"bev": "elektrisch", "phev": "Plug-in-Hybrid", "petrol": "Benziner", "diesel": "Diesel"},
        "powertrain_short": {"bev": "Elektrisch", "phev": "Plug-in-Hybrid", "petrol": "Benziner", "diesel": "Diesel"},
        "body": {"gran_coupe": "Gran Coupé", "touring": "Kombi (Touring)", "sav": "SUV (SAV)",
                 "tourer": "Kompaktvan (Tourer)", "sedan": "Limousine"},
        "field": {"budget_max": "Budget", "powertrain_preferred": "Antriebswunsch",
                  "powertrain_required": "Antriebsvorgabe", "min_seats": "Sitze", "child_seats": "Kindersitze",
                  "long_distance": "Langstrecke", "towing_kg": "Anhängelast", "min_trunk_l": "Kofferraumgröße",
                  "body_styles": "Karosserie", "sportiness": "Komfort/Sport", "must_have_options": "Wunschoptionen"},
    },
}

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "or": "or",
        # needs ("what I understood")
        "need_budget": "Budget up to {amount}",
        "need_must_be": "Must be {pts}",
        "need_prefers": "Prefers {pts}",
        "need_child_seat": "{n} child seat",
        "need_child_seats": "{n} child seats",
        "need_min_seats": "At least {n} seats",
        "need_long_distance": "Regular long-distance trips",
        "need_bike_carrier": "Bike carrier",
        "need_towing": "Towing {kg} kg",
        "need_trunk": "Boot ≥ {l} l",
        "need_comfort": "Comfort-focused",
        "need_sporty": "Sporty",
        "need_balanced": "Balanced comfort/sport",
        "need_must_have": "Must have: {names}",
        # components
        "slider_prompt": "What matters more to you on the road?",
        "slider_left": "Comfort",
        "slider_right": "Sporty",
        "hl_range": "{km} km range",
        "hl_phev_range": "{km} km electric · {total} km total",
        "hl_seats": "{n} seats",
        "hl_boot": "{l} l boot",
        "hl_tows": "tows {kg} kg",
        "title_recommended": "Recommended for you",
        "title_tradeoffs": "Possible trade-offs",
        "title_options": "Suggested options",
        "cmp_price": "Price as needed",
        "cmp_powertrain": "Powertrain",
        "cmp_electric_range": "Electric range",
        "cmp_total_range": "Total range",
        "cmp_dc": "DC charging",
        "cmp_seats": "Seats",
        "cmp_child_seats": "3 child seats in rear",
        "cmp_boot": "Boot",
        "cmp_towing": "Towing",
        "cmp_fits": "Meets your needs",
        "yes": "Yes",
        "no": "No",
        "not_fully": "Not fully",
        # conversation
        "greeting": "Hi! I'll help you find and configure the right car. Tell me how you'll use it - who travels with "
                    "you, typical trips, powertrain preferences and budget. I'll only ask what I need.",
        "examples_prompt": "Or start from an example:",
        "example_1": "I need a family car for regular long-distance travel. I prefer electric, need room for three "
                     "children, and do not want to spend more than EUR 85,000.",
        "example_2": "A sporty electric car for commuting, around €60k",
        "example_3": "We need 7 seats and tow a caravan",
        "llm_unavailable": "The AI assistant is temporarily unavailable - continuing in guided mode.",
        "echo_configure": "Configure the {model}",
        "echo_preference": "Preference: {pct}% sporty",
        "echo_tradeoff": "Accept: {label}",
        "echo_tradeoff_plain": "Accept trade-off",
        "echo_remove_need": "Remove requirement: {field}",
        "echo_summary": "Show summary",
        "pick_model_first": "Pick a model first - then I can summarise your configuration.",
        "added_for_needs": "Added {name} because your requirements need it.",
        "tradeoff_assumption": "Accepted trade-off: {label}",
        "voice_too_long": "That recording was too long. Please keep it a little shorter.",
        "voice_empty": "Nothing was recorded.",
        "voice_stt_down": "Speech recognition is unavailable right now.",
        "voice_tts_down": "Speech output is unavailable right now.",
    },
    "de": {
        "or": "oder",
        "need_budget": "Budget bis {amount}",
        "need_must_be": "Muss {pts} sein",
        "need_prefers": "Bevorzugt {pts}",
        "need_child_seat": "{n} Kindersitz",
        "need_child_seats": "{n} Kindersitze",
        "need_min_seats": "Mindestens {n} Sitze",
        "need_long_distance": "Regelmäßig Langstrecke",
        "need_bike_carrier": "Fahrradträger",
        "need_towing": "Anhängelast {kg} kg",
        "need_trunk": "Kofferraum ≥ {l} l",
        "need_comfort": "Komfortbetont",
        "need_sporty": "Sportlich",
        "need_balanced": "Ausgewogen zwischen Komfort und Sport",
        "need_must_have": "Gewünscht: {names}",
        "slider_prompt": "Was ist Ihnen beim Fahren wichtiger?",
        "slider_left": "Komfort",
        "slider_right": "Sportlich",
        "hl_range": "{km} km Reichweite",
        "hl_phev_range": "{km} km elektrisch · {total} km gesamt",
        "hl_seats": "{n} Sitze",
        "hl_boot": "{l} l Kofferraum",
        "hl_tows": "zieht {kg} kg",
        "title_recommended": "Für Sie empfohlen",
        "title_tradeoffs": "Mögliche Kompromisse",
        "title_options": "Vorgeschlagene Optionen",
        "cmp_price": "Preis wie benötigt",
        "cmp_powertrain": "Antrieb",
        "cmp_electric_range": "Elektrische Reichweite",
        "cmp_total_range": "Gesamtreichweite",
        "cmp_dc": "DC-Laden",
        "cmp_seats": "Sitze",
        "cmp_child_seats": "3 Kindersitze hinten",
        "cmp_boot": "Kofferraum",
        "cmp_towing": "Anhängelast",
        "cmp_fits": "Erfüllt Ihre Anforderungen",
        "yes": "Ja",
        "no": "Nein",
        "not_fully": "Nicht ganz",
        "greeting": "Hallo! Ich helfe Ihnen, das passende Auto zu finden und zu konfigurieren. Erzählen Sie mir, wie "
                    "Sie es nutzen – wer mitfährt, typische Strecken, Antriebswünsche und Budget. Ich frage nur, was "
                    "ich wirklich brauche.",
        "examples_prompt": "Oder starten Sie mit einem Beispiel:",
        "example_1": "Ich brauche ein Familienauto für regelmäßige Langstrecken. Am liebsten elektrisch, mit Platz "
                     "für drei Kinder und für höchstens 85.000 €.",
        "example_2": "Ein sportliches Elektroauto zum Pendeln, um die 60.000 €",
        "example_3": "Wir brauchen 7 Sitze und ziehen einen Wohnwagen",
        "llm_unavailable": "Der KI-Assistent ist gerade nicht erreichbar – es geht im geführten Modus weiter.",
        "echo_configure": "{model} konfigurieren",
        "echo_preference": "Vorliebe: {pct} % sportlich",
        "echo_tradeoff": "Übernehmen: {label}",
        "echo_tradeoff_plain": "Kompromiss übernehmen",
        "echo_remove_need": "Anforderung entfernen: {field}",
        "echo_summary": "Zusammenfassung anzeigen",
        "pick_model_first": "Wählen Sie zuerst ein Modell – dann fasse ich Ihre Konfiguration zusammen.",
        "added_for_needs": "{name} hinzugefügt, weil Ihre Anforderungen es erfordern.",
        "tradeoff_assumption": "Kompromiss übernommen: {label}",
        "voice_too_long": "Die Aufnahme war zu lang. Bitte fassen Sie sich etwas kürzer.",
        "voice_empty": "Es wurde nichts aufgenommen.",
        "voice_stt_down": "Die Spracherkennung ist gerade nicht verfügbar.",
        "voice_tts_down": "Die Sprachausgabe ist gerade nicht verfügbar.",
    },
}

assert MESSAGES["en"].keys() == MESSAGES["de"].keys(), "every message needs a German version"
