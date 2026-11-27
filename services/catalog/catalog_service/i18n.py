"""Languages for everything the catalog service says: catalog texts, rule messages, reasons.

The language comes from the request's Accept-Language header (``en`` default, ``de``) and is held in a
context variable for the duration of the request, so the rules engine and recommender don't need to pass
it around. Catalog data in other languages lives in ``data/i18n/<lang>.json`` as an overlay of the
English texts; ids, prices and rules are the same in every language.
"""

from __future__ import annotations

from contextvars import ContextVar

LANGUAGES = ("en", "de")
DEFAULT = "en"

current: ContextVar[str] = ContextVar("lang", default=DEFAULT)


def lang() -> str:
    return current.get()


def pick(accept_language: str | None) -> str:
    """First supported language in an Accept-Language header ('de-DE,de;q=0.9' -> 'de')."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGUAGES:
            return code
    return DEFAULT


def num(value: float) -> str:
    text = f"{value:,.0f}"
    return text.replace(",", ".") if lang() == "de" else text


def eur(value: float) -> str:
    return f"{num(value)} €" if lang() == "de" else f"€{num(value)}"


def t(key: str, **kw) -> str:
    return MESSAGES[lang()][key].format(**kw)


def group_word(name: str) -> str:
    """Group names inside sentences: 'Only one wheels choice' vs. German nouns, which stay capitalised."""
    return name if lang() == "de" else name.lower()


POWERTRAIN = {
    "en": {"bev": "Fully electric", "phev": "Plug-in hybrid", "petrol": "Petrol", "diesel": "Diesel"},
    "de": {"bev": "Vollelektrisch", "phev": "Plug-in-Hybrid", "petrol": "Benziner", "diesel": "Diesel"},
}
BODY = {
    "en": {"gran_coupe": "gran coupe", "touring": "touring", "sav": "sav", "tourer": "tourer", "sedan": "sedan"},
    "de": {"gran_coupe": "Gran Coupé", "touring": "Touring", "sav": "SAV", "tourer": "Active Tourer", "sedan": "Limousine"},
}


def powertrain(code: str, inline: bool = False) -> str:
    label = POWERTRAIN[lang()][code]
    return label.lower() if inline and lang() == "en" else label


def body(code: str) -> str:
    return BODY[lang()][code]


MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # rules engine: validation
        "unknown_option": "Unknown option '{oid}'.",
        "not_available": "{opt} is not available on the {model}.{hint}",
        "available_on": " It is available on: {models}.",
        "requires": "{opt} requires {req}.",
        "excluded": "{opt} cannot be combined with {other}.",
        "group_conflict": "Only one {group} choice is allowed: {names}.",
        "group_missing": "A {group} choice is required.",
        # price lines and availability
        "standard": "Standard equipment",
        "included_in": "Included in {pkg}",
        "required_by": "Required by {names}",
        "not_offered_on": "Not offered on the {series}",
        "saving_with_dependents": "{name} (and {others}, which need it)",
        # adding
        "no_such_option_catalog": "There is no option called '{oid}' in the catalog.",
        "already_included": " (included in {pkg})",
        "already_part": "{opt} is already part of the configuration{where}.",
        "dependency_unavailable": "{opt} needs {dep}, which is not offered on the {model}.",
        "would_replace": "{new} would replace {old}",
        "cannot_combine": "{new} cannot be combined with {old}",
        "part_of_package": "{opt} is part of the {pkg}",
        "comes_with": "comes with {pkg}",
        "dependent_requires": "{dep} requires {opt}",
        "add_conflict": "{opt} conflicts with your configuration: {reasons}. Adding it removes {removed}.",
        "resolve_add": "Add {opt}, remove {removed}",
        "resolve_keep": "Keep {names}",
        "added": "Added {opt}.",
        "package_includes": "{pkg} includes {items} at no extra cost.",
        "also_added": "Also added {dep} because {opt} requires it.",
        "removed_because": "Removed {opt}: {reason}.",
        # removing
        "no_such_option": "There is no option called '{oid}'.",
        "remove_package_item": "{opt} is part of the {pkg}. Removing it means removing the package.",
        "resolve_remove": "Remove {opt}",
        "resolve_keep_package": "Keep the package",
        "not_in_configuration": "{opt} is not in the configuration.",
        "not_removable": "{opt} is the standard {group} choice; pick another {group} option instead.",
        "required_by_selected": "{names} requires {opt}.",
        "resolve_remove_both": "Remove {opt} and {names}",
        "resolve_keep_one": "Keep {opt}",
        "removed": "Removed {opt}",
        "removed_dependents": " and {names} (which require it)",
        "removed_contents": " including {names}",
        "restored": "{opt} restored as standard.",
        "dropped": "Dropped {opt}: {reason}",
        "and": "and",
        # requirement violations
        "v_body": "Body style is {body}",
        "v_body_relax": "Consider other body styles",
        "v_powertrain": "{has}, not {wanted}",
        "v_powertrain_relax": "Also consider {pt}",
        "v_seats": "Seats {seats}, you need {need}",
        "v_seats_relax": "Accept {seats} seats",
        "v_child_seats": "Rear bench does not fit three child seats side by side",
        "v_child_seats_relax": "Plan for two child seats in the rear",
        "v_no_hitch": "No tow hitch available",
        "v_skip_towing": "Skip towing",
        "v_tow_max": "Tows max {max} kg, you need {need} kg",
        "v_tow_relax": "Tow up to {max} kg",
        "v_hitch_missing": "Tow hitch not yet added",
        "v_range": "Range {range} km, below the {min} km we recommend for regular long trips",
        "v_range_relax": "Accept {range} km range",
        "v_trunk": "Boot {trunk} l, you asked for {need} l",
        "v_trunk_relax": "Accept {trunk} l boot",
        "v_option_not_offered": "{name} is not offered",
        "v_option_not_added": "{name} not yet added",
        "v_option_relax": "Do without {name}",
        "v_budget": "{total} is {over} over your {budget} budget",
        "v_budget_relax": "Raise budget to {total}",
        # reasons for a model
        "r_preferred": "{pt}, as you prefer",
        "r_phev": "Plug-in hybrid: ~{km} km electric for daily driving, no charging stops on trips",
        "r_bev_long": "{range} km range and {kw} kW fast charging for long trips",
        "r_ice_long": "{km} km total range, refuel in minutes",
        "r_three_child_seats": "Rear bench fits three child seats side by side",
        "r_boot": "{trunk} l boot for family luggage",
        "r_sporty": "Sporty character matches your preference",
        "r_comfort": "Comfort-oriented, matches your preference",
        "r_tows": "Tows up to {kg} kg",
        "r_budget": "From {price}, {headroom} below your budget",
        "tradeoff": "{name} would fit ({violations}). {gains}",
        "explain_fits": "{n} model(s) meet all requirements",
        "explain_more": "; {n} more would fit with a small compromise",
        "explain_near": "No model meets every requirement. The closest options each need one compromise.",
        "explain_none": "No model is close to the requirements; consider relaxing several constraints.",
        # reasons for an option
        "o_long_distance": "Recommended for regular long-distance trips",
        "o_family": "Useful for family travel",
        "o_sport": "Matches your sporty preference",
        "o_comfort": "Matches your comfort preference",
        "o_towing": "Needed for towing",
        "s_long_distance": "Supports your regular long-distance trips",
        "s_comfort": "Adds comfort",
        "s_bike_carrier": "Needed for your bike carrier",
        "s_tow": "Needed to tow {kg} kg",
        "s_seats": "Needed for the seats you asked for",
        "s_asked": "You asked for this",
        "s_choice": "Your choice",
    },
    "de": {
        "unknown_option": "Unbekannte Option '{oid}'.",
        "not_available": "{opt} ist für den {model} nicht erhältlich.{hint}",
        "available_on": " Erhältlich für: {models}.",
        "requires": "{opt} erfordert {req}.",
        "excluded": "{opt} ist nicht mit {other} kombinierbar.",
        "group_conflict": "Bei {group} ist nur eine Auswahl möglich: {names}.",
        "group_missing": "Bei {group} ist eine Auswahl erforderlich.",
        "standard": "Serienausstattung",
        "included_in": "Enthalten in: {pkg}",
        "required_by": "Erforderlich für {names}",
        "not_offered_on": "Für den {series} nicht erhältlich",
        "saving_with_dependents": "{name} (und {others}, das darauf aufbaut)",
        "no_such_option_catalog": "Im Katalog gibt es keine Option '{oid}'.",
        "already_included": " (enthalten in: {pkg})",
        "already_part": "{opt} ist bereits Teil der Konfiguration{where}.",
        "dependency_unavailable": "{opt} benötigt {dep}, das für den {model} nicht erhältlich ist.",
        "would_replace": "{new} statt {old}",
        "cannot_combine": "{new} ist nicht mit {old} kombinierbar",
        "part_of_package": "{opt} ist Teil von {pkg}",
        "comes_with": "gehört zu {pkg}",
        "dependent_requires": "{dep} erfordert {opt}",
        "add_conflict": "{opt} passt nicht zu Ihrer Konfiguration: {reasons}. Beim Hinzufügen wird entfernt: {removed}.",
        "resolve_add": "{opt} hinzufügen, {removed} entfernen",
        "resolve_keep": "{names} behalten",
        "added": "{opt} hinzugefügt.",
        "package_includes": "{pkg} enthält {items} ohne Aufpreis.",
        "also_added": "{dep} ebenfalls hinzugefügt, weil {opt} es erfordert.",
        "removed_because": "{opt} entfernt: {reason}.",
        "no_such_option": "Es gibt keine Option '{oid}'.",
        "remove_package_item": "{opt} ist Teil von {pkg}. Um es zu entfernen, muss das Paket entfernt werden.",
        "resolve_remove": "{opt} entfernen",
        "resolve_keep_package": "Paket behalten",
        "not_in_configuration": "{opt} ist nicht in der Konfiguration.",
        "not_removable": "{opt} ist die Serienausstattung bei {group}; wählen Sie stattdessen eine andere Option.",
        "required_by_selected": "{names} erfordert {opt}.",
        "resolve_remove_both": "{opt} und {names} entfernen",
        "resolve_keep_one": "{opt} behalten",
        "removed": "{opt} entfernt",
        "removed_dependents": ", ebenso {names} (das darauf aufbaut)",
        "removed_contents": ", einschließlich {names}",
        "restored": "{opt} als Serienausstattung wiederhergestellt.",
        "dropped": "{opt} nicht übernommen: {reason}",
        "and": "und",
        "v_body": "Karosserie: {body}",
        "v_body_relax": "Auch andere Karosserieformen",
        "v_powertrain": "{has}, nicht {wanted}",
        "v_powertrain_relax": "Auch {pt} in Betracht ziehen",
        "v_seats": "{seats} Sitze, Sie benötigen {need}",
        "v_seats_relax": "{seats} Sitze akzeptieren",
        "v_child_seats": "Auf die Rückbank passen keine drei Kindersitze nebeneinander",
        "v_child_seats_relax": "Mit zwei Kindersitzen hinten planen",
        "v_no_hitch": "Keine Anhängerkupplung erhältlich",
        "v_skip_towing": "Auf Anhängerbetrieb verzichten",
        "v_tow_max": "Zieht max. {max} kg, Sie benötigen {need} kg",
        "v_tow_relax": "Bis {max} kg ziehen",
        "v_hitch_missing": "Anhängerkupplung noch nicht hinzugefügt",
        "v_range": "Reichweite {range} km, unter den {min} km, die wir für regelmäßige Langstrecken empfehlen",
        "v_range_relax": "{range} km Reichweite akzeptieren",
        "v_trunk": "Kofferraum {trunk} l, gewünscht sind {need} l",
        "v_trunk_relax": "{trunk} l Kofferraum akzeptieren",
        "v_option_not_offered": "{name} ist nicht erhältlich",
        "v_option_not_added": "{name} noch nicht hinzugefügt",
        "v_option_relax": "Auf {name} verzichten",
        "v_budget": "{total} liegt {over} über Ihrem Budget von {budget}",
        "v_budget_relax": "Budget auf {total} erhöhen",
        "r_preferred": "{pt}, wie gewünscht",
        "r_phev": "Plug-in-Hybrid: ca. {km} km elektrisch im Alltag, keine Ladestopps auf Reisen",
        "r_bev_long": "{range} km Reichweite und {kw} kW Schnellladen für lange Strecken",
        "r_ice_long": "{km} km Gesamtreichweite, in Minuten nachgetankt",
        "r_three_child_seats": "Rückbank für drei Kindersitze nebeneinander",
        "r_boot": "{trunk} l Kofferraum für das Familiengepäck",
        "r_sporty": "Sportlicher Charakter, wie gewünscht",
        "r_comfort": "Komfortorientiert, wie gewünscht",
        "r_tows": "Zieht bis zu {kg} kg",
        "r_budget": "Ab {price}, {headroom} unter Ihrem Budget",
        "tradeoff": "{name} würde passen ({violations}). {gains}",
        "explain_fits": "{n} Modell(e) erfüllen alle Anforderungen",
        "explain_more": "; {n} weitere würden mit einem kleinen Kompromiss passen",
        "explain_near": "Kein Modell erfüllt alle Anforderungen. Die nächstliegenden brauchen jeweils einen Kompromiss.",
        "explain_none": "Kein Modell kommt den Anforderungen nahe; lockern Sie am besten mehrere Vorgaben.",
        "o_long_distance": "Empfohlen für regelmäßige Langstrecken",
        "o_family": "Praktisch für Familienreisen",
        "o_sport": "Passt zu Ihrer sportlichen Vorliebe",
        "o_comfort": "Passt zu Ihrem Komfortwunsch",
        "o_towing": "Für den Anhängerbetrieb nötig",
        "s_long_distance": "Unterstützt Ihre regelmäßigen Langstrecken",
        "s_comfort": "Mehr Komfort",
        "s_bike_carrier": "Für Ihren Fahrradträger nötig",
        "s_tow": "Nötig, um {kg} kg zu ziehen",
        "s_seats": "Für die gewünschte Sitzanzahl nötig",
        "s_asked": "Von Ihnen gewünscht",
        "s_choice": "Ihre Wahl",
    },
}

assert MESSAGES["en"].keys() == MESSAGES["de"].keys(), "every message needs a German version"
