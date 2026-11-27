"""Rule-based language understanding for the offline (no API key) mode, in English and German.

Deliberately simple and transparent: keyword and regex patterns that cover
the demo journey and common phrasings. Both languages are matched at once, so a
German phrase works in the English interface too. The LLM agent replaces this
entirely when an API key is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .i18n import lang

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "ein": 1, "eins": 1, "einem": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
                "sechs": 6, "sieben": 7, "acht": 8}
NUM = r"(\d+|" + "|".join(NUMBER_WORDS) + r")"

MODEL_PATTERNS = [
    (r"\bi5\b", "i5_touring_edrive40"),
    (r"\bi4\b", "i4_edrive40"),
    (r"\bix1\b", "ix1_xdrive30"),
    (r"\bix\b(?!1)", "ix_xdrive45"),
    (r"\bx5\b", "x5_xdrive50e"),
    (r"\bx7\b", "x7_xdrive40d"),
    (r"\b520d\b|\b5 series\b|\b5er\b", "touring_520d"),
    (r"active tourer|\b225e\b", "active_tourer_225e"),
]

OPTION_PATTERNS = [
    (r"head[- ]?up|\bhud\b", "hud"),
    (r"tow(ing)? hitch|tow bar|towbar|anhängerkupplung|\bahk\b", "tow_hitch"),
    (r"panoram|sunroof|glass roof|glasdach|schiebedach", "panorama_roof"),
    (r"roof rails?|roof box|dachreling|dachbox", "roof_rails"),
    (r"massage|ventilated seats|comfort seats|belüftete sitze|komfortsitze", "seats_comfort"),
    (r"sport seats|sportsitze", "seats_sport"),
    (r"m sport", "pkg_m_sport"),
    (r"travel (&|and) comfort|reise.{0,4}komfort", "pkg_travel_comfort"),
    (r"driving assist|adaptive cruise|highway assist|fahrassistent|abstandstempomat|autobahnassistent", "pkg_driving_assistant_pro"),
    (r"parking assist|360|surround view camera|parkassistent|einparkhilfe|rückfahrkamera", "pkg_parking_assistant"),
    (r"harman", "audio_harman"),
    (r"bowers|b&w", "audio_bw"),
    (r"third row|7 seats option|third-row|dritte sitzreihe", "third_row"),
    (r"rear[- ](seat[- ])?entertainment|screens? (in the|for the) (back|rear)|fond.?entertainment|bildschirme hinten",
     "rear_entertainment"),
    (r"22 ?kw", "charging_22kw"),
    (r"21\"|21 inch|21-inch|21 zoll|21-zoll", "wheels_21_m"),
    (r"20\"|20 inch|20-inch|20 zoll|20-zoll", "wheels_20_sport"),
    (r"black sapphire|black paint|saphirschwarz|schwarze lackierung", "paint_black_sapphire"),
    (r"portim|blue paint|blaue lackierung", "paint_portimao_blue"),
    (r"heated steering|lenkradheizung|beheiztes lenkrad", "heated_steering"),
    (r"4[- ]zone|rear climate|4[- ]zonen|fondklima|klima hinten", "rear_climate"),
]

ASSUMPTIONS = {
    "en": {
        "three_child_seats": "{n} children → {n} child seats, so the rear bench must fit three side by side",
        "long_distance": "Regular long-distance travel → at least 450 km real-world range for electric models",
        "caravan": "Caravan → about 1,500 kg towing capacity",
    },
    "de": {
        "three_child_seats": "{n} Kinder → {n} Kindersitze, die Rückbank muss also drei nebeneinander aufnehmen",
        "long_distance": "Regelmäßige Langstrecken → bei Elektroautos mindestens 450 km Reichweite im Alltag",
        "caravan": "Wohnwagen → etwa 1.500 kg Anhängelast",
    },
}


def _assume(key: str, **kw) -> str:
    return ASSUMPTIONS[lang()][key].format(**kw)


def _num(token: str) -> int:
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


@dataclass
class Parsed:
    patch: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    model_ids: list[str] = field(default_factory=list)
    add_options: list[str] = field(default_factory=list)
    remove_options: list[str] = field(default_factory=list)
    wants_compare: bool = False
    wants_summary: bool = False
    wants_alternatives: bool = False
    wants_select: bool = False

    @property
    def empty(self) -> bool:
        return not (self.patch or self.model_ids or self.add_options or self.remove_options
                    or self.wants_compare or self.wants_summary or self.wants_alternatives)


def parse_budget(text: str) -> int | None:
    t = text.lower().replace(" ", " ")
    m = re.search(r"(\d{2,3})\s?(?:k|tsd\.?|tausend)\b", t)
    if m:
        return int(m.group(1)) * 1000
    for m in re.finditer(r"(\d{1,3}(?:[.,\s]\d{3})+|\d{5,6})(?![\d])\s*(?:€|eur|euro)?", t):
        value = int(re.sub(r"[.,\s]", "", m.group(1)))
        after = t[m.end():m.end() + 4]
        if 10_000 <= value <= 500_000 and "kg" not in after and "km" not in after:
            return value
    return None


def parse(text: str) -> Parsed:
    t = text.lower()
    p = Parsed()

    # budget
    if re.search(r"flexible|no (fixed )?budget|budget (is )?open|money is no|flexibel|kein (festes )?budget|"
                 r"budget (ist )?offen|geld spielt keine", t):
        p.patch["budget_max"] = None
    else:
        budget = parse_budget(t)
        if budget:
            p.patch["budget_max"] = budget

    # powertrain
    negated_electric = re.search(r"(not|no|don't want( an?)?)\s+(fully\s+)?electric|"
                                 r"(nicht|kein(en)?)\s+(rein\s+)?(elektr|e-auto)", t)
    if re.search(r"(must|has to|only|needs? to)\s+(be\s+)?(fully\s+)?electric|"
                 r"(muss|nur|ausschließlich)\s+(\w+\s+)?(elektr|e-auto)", t):
        p.patch["powertrain_required"] = ["bev"]
    elif (re.search(r"electric|\bev\b|\bbev\b|battery|elektr|e-auto|stromer", t) and not negated_electric
          and "hybrid" not in t):
        p.patch["powertrain_preferred"] = ["bev"]
    if re.search(r"hybrid|phev|plug-in", t) and not re.search(r"no (plug-in )?hybrid|kein(en)? (plug-in-)?hybrid", t):
        if re.search(r"electric|elektr", t) and not negated_electric:
            p.patch["powertrain_preferred"] = ["bev", "phev"]
        else:
            p.patch["powertrain_preferred"] = ["phev"]
        if re.search(r"(hybrid|plug-in).{0,20}(is )?(fine|ok|okay|acceptable)|open to|"
                     r"hybrid.{0,20}(ist )?(auch )?(ok|okay|in ordnung)|offen für", t):
            p.patch["powertrain_required"] = None
    if re.search(r"\bdiesel\b", t) and not re.search(r"no diesel|kein(en)? diesel", t):
        p.patch["powertrain_preferred"] = ["diesel"]
    if re.search(r"any (powertrain|engine)|don't mind the (engine|powertrain)|antrieb (ist )?egal|egal welcher antrieb", t):
        p.patch["powertrain_preferred"] = None
        p.patch["powertrain_required"] = None

    # family / seats
    m = re.search(NUM + r"\s+(?:small\s+|young\s+|kleine[n]?\s+)?(?:children|kids|child seats|child|kid|kindersitze|kindersitz|kindern|kinder|kind)\b", t)
    if m:
        n = _num(m.group(1))
        p.patch["child_seats"] = n
        if n >= 3:
            p.assumptions.append(_assume("three_child_seats", n=n))
    m = re.search(NUM + r"[\s-]*(?:seats|seater|sitze|sitzer|sitzplätze)\b", t)
    if m:
        p.patch["min_seats"] = _num(m.group(1))
    m = re.search(r"(\d)\s*[–-]\s*(\d)\s+(?:people|personen|leute)", t)
    if m:
        p.patch["min_seats"] = max(int(m.group(1)), int(m.group(2)))
    elif re.search(r"just me|two of us|couple|nur ich|zu zweit|wir zwei", t):
        p.patch["min_seats"] = None
        p.patch["child_seats"] = None

    # usage
    if re.search(r"long[- ]distance|road ?trips?|long trips|motorway|autobahn|travel a lot|holiday trips|"
                 r"langstreck|lange (strecken|fahrten|reisen)|urlaubsfahrten|viel unterwegs", t):
        p.patch["long_distance"] = True
        p.assumptions.append(_assume("long_distance"))
    if re.search(r"mostly (in the )?city|short trips|commut|stadt|kurze strecken|pendel", t) and "lang" not in t \
            and "long" not in t:
        p.patch["long_distance"] = False

    # towing ("Anhängerkupplung" names the option, not a trailer)
    if re.search(r"no towing|don't tow|do not tow|nothing to tow|no trailer|^no$|nichts ziehen|ziehe nichts|"
                 r"kein(en)? anhänger(?!kupplung)|^nein$", t):
        p.patch["towing_kg"] = None
    elif re.search(r"bike (carrier|rack)|fahrradträger|radträger", t):
        p.patch["towing_kg"] = 0
    elif re.search(r"tow|trailer|caravan|horse box|zieh|anhänger(?!kupplung)|wohnwagen|pferdeanhänger", t):
        m = re.search(r"(\d[\d.,]*)\s*kg", t)
        if m:
            p.patch["towing_kg"] = int(re.sub(r"[.,]", "", m.group(1)))
        elif "caravan" in t or "wohnwagen" in t:
            p.patch["towing_kg"] = 1500
            p.assumptions.append(_assume("caravan"))
        elif "trailer" in t or re.search(r"anhänger(?!kupplung)", t):
            p.patch["towing_kg"] = 750

    # character
    if re.search(r"sporty|dynamic|fun to drive|performance|sportlich|dynamisch|fahrspaß", t):
        p.patch["sportiness"] = 0.8
    elif re.search(r"(prefer|more|prioriti[sz]e|value|focus on|mainly) comfort\b|comfortable|relaxed|quiet|"
                   r"komfortabel|bequem|entspannt|leise|(mehr|lieber|eher) komfort\b|komfort ist", t):
        p.patch["sportiness"] = 0.2

    # space & body
    if re.search(r"big boot|large boot|lots of luggage|large trunk|big trunk|a lot of luggage|"
                 r"große[nr]? kofferraum|viel gepäck", t):
        p.patch["min_trunk_l"] = 550
    if re.search(r"\bsuv\b|\bsav\b", t):
        p.patch["body_styles"] = ["sav"]
    elif re.search(r"estate|wagon|touring\b|\bkombi\b", t) and not re.search(r"\bi5\b|520d", t):
        p.patch["body_styles"] = ["touring"]

    # models & options
    for pattern, mid in MODEL_PATTERNS:
        if re.search(pattern, t) and mid not in p.model_ids:
            p.model_ids.append(mid)
    removing = re.search(r"\b(remove|without|drop|no longer|don't need|skip|take off|entfern\w*|ohne|weglassen|"
                         r"brauche (ich )?kein\w*|nicht mehr|streichen|raus)\b", t)
    for pattern, oid in OPTION_PATTERNS:
        if re.search(pattern, t):
            (p.remove_options if removing else p.add_options).append(oid)

    p.wants_compare = bool(re.search(r"compar|difference|versus|\bvs\b|vergleich|unterschied", t))
    p.wants_summary = bool(re.search(r"summary|that's it|\bdone\b|\bfinish|looks good|wrap (it )?up|overview|"
                                     r"zusammenfassung|das war'?s|\bfertig\b|passt so|übersicht|abschließen", t))
    p.wants_alternatives = bool(re.search(r"alternative|other models|something else|cheaper model|andere modelle|"
                                          r"etwas anderes|günstigere[sn]? modell", t))
    p.wants_select = bool(re.search(r"configure|\btake\b|go with|choose|\bpick\b|let's do|select|start with|switch to|"
                                    r"konfigurier|\bnehme|\bwähle|auswählen|entscheide mich|starte mit|wechsel", t))
    return p
