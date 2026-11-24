"""Rule-based language understanding for the offline (no API key) mode.

Deliberately simple and transparent: keyword and regex patterns that cover
the demo journey and common phrasings. The LLM agent replaces this
entirely when an API key is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
NUM = r"(\d+|one|two|three|four|five|six|seven|eight)"

MODEL_PATTERNS = [
    (r"\bi5\b", "i5_touring_edrive40"),
    (r"\bi4\b", "i4_edrive40"),
    (r"\bix1\b", "ix1_xdrive30"),
    (r"\bix\b(?!1)", "ix_xdrive45"),
    (r"\bx5\b", "x5_xdrive50e"),
    (r"\bx7\b", "x7_xdrive40d"),
    (r"\b520d\b|\b5 series\b", "touring_520d"),
    (r"active tourer|\b225e\b", "active_tourer_225e"),
]

OPTION_PATTERNS = [
    (r"head[- ]?up|\bhud\b", "hud"),
    (r"tow(ing)? hitch|tow bar|towbar", "tow_hitch"),
    (r"panoram|sunroof|glass roof", "panorama_roof"),
    (r"roof rails?|roof box", "roof_rails"),
    (r"massage|ventilated seats|comfort seats", "seats_comfort"),
    (r"sport seats", "seats_sport"),
    (r"m sport", "pkg_m_sport"),
    (r"travel (&|and) comfort", "pkg_travel_comfort"),
    (r"driving assist|adaptive cruise|highway assist", "pkg_driving_assistant_pro"),
    (r"parking assist|360|surround view camera", "pkg_parking_assistant"),
    (r"harman", "audio_harman"),
    (r"bowers|b&w", "audio_bw"),
    (r"third row|7 seats option|third-row", "third_row"),
    (r"rear[- ](seat[- ])?entertainment|screens? (in the|for the) (back|rear)", "rear_entertainment"),
    (r"22 ?kw", "charging_22kw"),
    (r"21\"|21 inch|21-inch", "wheels_21_m"),
    (r"20\"|20 inch|20-inch", "wheels_20_sport"),
    (r"black sapphire|black paint", "paint_black_sapphire"),
    (r"portim|blue paint", "paint_portimao_blue"),
    (r"heated steering", "heated_steering"),
    (r"4[- ]zone|rear climate", "rear_climate"),
]


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
    t = text.lower().replace(" ", " ")
    m = re.search(r"(\d{2,3})\s?k\b", t)
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
    if re.search(r"flexible|no (fixed )?budget|budget (is )?open|money is no", t):
        p.patch["budget_max"] = None
    else:
        budget = parse_budget(t)
        if budget:
            p.patch["budget_max"] = budget

    # powertrain
    negated_electric = re.search(r"(not|no|don't want( an?)?)\s+(fully\s+)?electric", t)
    if re.search(r"(must|has to|only|needs? to)\s+(be\s+)?(fully\s+)?electric", t):
        p.patch["powertrain_required"] = ["bev"]
    elif re.search(r"electric|\bev\b|\bbev\b|battery", t) and not negated_electric and "hybrid" not in t:
        p.patch["powertrain_preferred"] = ["bev"]
    if re.search(r"hybrid|phev|plug-in", t) and not re.search(r"no (plug-in )?hybrid", t):
        if re.search(r"electric", t) and not negated_electric:
            p.patch["powertrain_preferred"] = ["bev", "phev"]
        else:
            p.patch["powertrain_preferred"] = ["phev"]
        if re.search(r"(hybrid|plug-in).{0,20}(is )?(fine|ok|okay|acceptable)|open to", t):
            p.patch["powertrain_required"] = None
    if re.search(r"\bdiesel\b", t) and not re.search(r"no diesel", t):
        p.patch["powertrain_preferred"] = ["diesel"]
    if re.search(r"any (powertrain|engine)|don't mind the (engine|powertrain)", t):
        p.patch["powertrain_preferred"] = None
        p.patch["powertrain_required"] = None

    # family / seats
    m = re.search(NUM + r"\s+(?:small\s+|young\s+)?(?:children|kids|child seats|child|kid)", t)
    if m:
        n = _num(m.group(1))
        p.patch["child_seats"] = n
        if n >= 3:
            p.assumptions.append(f"{n} children → {n} child seats, so the rear bench must fit three side by side")
    m = re.search(NUM + r"[\s-]*(?:seats|seater)", t)
    if m:
        p.patch["min_seats"] = _num(m.group(1))
    m = re.search(r"(\d)\s*[–-]\s*(\d)\s+people", t)
    if m:
        p.patch["min_seats"] = max(int(m.group(1)), int(m.group(2)))
    elif re.search(r"just me|two of us|couple", t):
        p.patch["min_seats"] = None
        p.patch["child_seats"] = None

    # usage
    if re.search(r"long[- ]distance|road ?trips?|long trips|motorway|autobahn|travel a lot|holiday trips", t):
        p.patch["long_distance"] = True
        p.assumptions.append("Regular long-distance travel → at least 450 km real-world range for electric models")
    if re.search(r"mostly (in the )?city|short trips|commut", t) and "long" not in t:
        p.patch["long_distance"] = False

    # towing
    if re.search(r"no towing|don't tow|do not tow|nothing to tow|no trailer|^no$", t):
        p.patch["towing_kg"] = None
    elif re.search(r"bike (carrier|rack)", t):
        p.patch["towing_kg"] = 0
    elif re.search(r"tow|trailer|caravan|horse box", t):
        m = re.search(r"(\d[\d.,]*)\s*kg", t)
        if m:
            p.patch["towing_kg"] = int(re.sub(r"[.,]", "", m.group(1)))
        elif "caravan" in t:
            p.patch["towing_kg"] = 1500
            p.assumptions.append("Caravan → about 1,500 kg towing capacity")
        elif "trailer" in t:
            p.patch["towing_kg"] = 750

    # character
    if re.search(r"sporty|dynamic|fun to drive|performance", t):
        p.patch["sportiness"] = 0.8
    elif re.search(r"(prefer|more|prioriti[sz]e|value|focus on|mainly) comfort\b|comfortable|relaxed|quiet", t):
        p.patch["sportiness"] = 0.2

    # space & body
    if re.search(r"big boot|large boot|lots of luggage|large trunk|big trunk|a lot of luggage", t):
        p.patch["min_trunk_l"] = 550
    if re.search(r"\bsuv\b|\bsav\b", t):
        p.patch["body_styles"] = ["sav"]
    elif re.search(r"estate|wagon|touring\b", t) and not re.search(r"\bi5\b|520d", t):
        p.patch["body_styles"] = ["touring"]

    # models & options
    for pattern, mid in MODEL_PATTERNS:
        if re.search(pattern, t) and mid not in p.model_ids:
            p.model_ids.append(mid)
    removing = re.search(r"\b(remove|without|drop|no longer|don't need|skip|take off)\b", t)
    for pattern, oid in OPTION_PATTERNS:
        if re.search(pattern, t):
            (p.remove_options if removing else p.add_options).append(oid)

    p.wants_compare = bool(re.search(r"compar|difference|versus|\bvs\b", t))
    p.wants_summary = bool(re.search(r"summary|that's it|\bdone\b|\bfinish|looks good|wrap (it )?up|overview", t))
    p.wants_alternatives = bool(re.search(r"alternative|other models|something else|cheaper model", t))
    p.wants_select = bool(re.search(r"configure|\btake\b|go with|choose|\bpick\b|let's do|select|start with|switch to", t))
    return p
