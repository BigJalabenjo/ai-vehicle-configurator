"""Builders for adaptive UI components.

The LLM decides *which* component to show; these builders fill them with
authoritative data from the catalog service, so prices, specs and validity on
screen never come from model-generated text.
"""

from __future__ import annotations

import uuid

from .domain import Requirements
from .i18n import eur, lang, num, t, words


def _id() -> str:
    return uuid.uuid4().hex[:8]


def question(prompt: str, choices: list[str], topic: str = "", allow_free_text: bool = True) -> dict:
    return {"type": "question", "id": _id(), "topic": topic, "prompt": prompt,
            "choices": [{"label": c} for c in choices][:6], "allow_free_text": allow_free_text}


def slider(req: Requirements, prompt: str | None = None) -> dict:
    return {"type": "slider", "id": _id(), "preference": "sportiness", "prompt": prompt or t("slider_prompt"),
            "left_label": t("slider_left"), "right_label": t("slider_right"),
            "value": req.sportiness if req.sportiness is not None else 0.5}


def model_card(ev: dict) -> dict:
    s = ev["specs"]
    return {
        "model_id": ev["model_id"],
        "name": ev["name"],
        "powertrain": words("powertrain_short")[ev["powertrain"]],
        "body": ev["body"],
        "base_price": ev["base_price"],
        "entry_price": ev["entry_price"],
        "fits": ev["fits"],
        "score": ev["score"],
        "reasons": ev["reasons"][:3],
        "violations": [v["message"] for v in ev["violations"]],
        "required_options": ev["required_options"],
        "highlights": _highlights(s),
    }


def _highlights(s: dict) -> list[str]:
    out = []
    if s.get("electric_range_km") and s["powertrain"] == "bev":
        out.append(t("hl_range", km=s["electric_range_km"]))
    elif s.get("electric_range_km"):
        out.append(t("hl_phev_range", km=s["electric_range_km"], total=num(s["total_range_km"])))
    else:
        out.append(t("hl_range", km=num(s["total_range_km"])))
    out.append(t("hl_seats", n=s["seats"]))
    out.append(t("hl_boot", l=s["trunk_l"]))
    if s.get("max_tow_kg"):
        out.append(t("hl_tows", kg=num(s["max_tow_kg"])))
    return out


def model_cards(evaluations: list[dict], title: str | None = None) -> dict:
    return {"type": "model_cards", "id": _id(), "title": title or t("title_recommended"), "cards": [model_card(e) for e in evaluations]}


def comparison(evaluations: list[dict]) -> dict:
    yes_no = lambda v: t("yes") if v else t("no")  # noqa: E731
    seconds = lambda v: f"{v} s".replace(".", ",") if lang() == "de" else f"{v} s"  # noqa: E731
    rows_spec = [
        (t("cmp_price"), lambda e: e["entry_price"], "min", eur),
        (t("cmp_powertrain"), lambda e: words("powertrain_short")[e["powertrain"]], None, str),
        (t("cmp_electric_range"), lambda e: e["specs"]["electric_range_km"] or 0, "max", lambda v: f"{v} km" if v else "—"),
        (t("cmp_total_range"), lambda e: e["specs"]["total_range_km"], "max", lambda v: f"{num(v)} km"),
        (t("cmp_dc"), lambda e: e["specs"]["dc_charge_kw"] or 0, "max", lambda v: f"{v} kW" if v else "—"),
        (t("cmp_seats"), lambda e: e["specs"]["seats"], "max", str),
        (t("cmp_child_seats"), lambda e: e["specs"]["rear_three_child_seats"], None, yes_no),
        (t("cmp_boot"), lambda e: e["specs"]["trunk_l"], "max", lambda v: f"{v} l"),
        (t("cmp_towing"), lambda e: e["specs"]["max_tow_kg"], "max", lambda v: f"{num(v)} kg" if v else "—"),
        ("0–100 km/h", lambda e: e["specs"]["acceleration_s"], "min", seconds),
        (t("cmp_fits"), lambda e: e["fits"], None, lambda v: t("yes") if v else t("not_fully")),
    ]
    rows = []
    for label, getter, best, fmt in rows_spec:
        raw = [getter(e) for e in evaluations]
        best_idx = None
        if best and len(set(raw)) > 1:
            target = min(raw) if best == "min" else max(raw)
            best_idx = raw.index(target)
        rows.append({"label": label, "values": [fmt(v) for v in raw], "best_index": best_idx})
    return {"type": "comparison", "id": _id(),
            "models": [{"model_id": e["model_id"], "name": e["name"]} for e in evaluations], "rows": rows}


def tradeoffs(items: list[dict], title: str | None = None) -> dict:
    return {"type": "tradeoffs", "id": _id(), "title": title or t("title_tradeoffs"),
            "items": [{"label": t["label"], "description": t["description"], "model_id": t["model_id"],
                       "patch": t["relax_patch"]} for t in items]}


def option_toggles(view: dict, option_ids: list[str] | None = None, title: str | None = None) -> dict:
    by_id = {o["id"]: o for o in view["catalog_options"]}
    if option_ids is None:
        option_ids = [o["id"] for o in view["catalog_options"] if o["recommended"]]
    options = [by_id[i] for i in option_ids if i in by_id]
    return {"type": "option_toggles", "id": _id(), "title": title or t("title_options"), "model_id": view["model_id"],
            "options": options}


def conflict(conflict_data: dict) -> dict:
    return {"type": "conflict", "id": _id(), "message": conflict_data["message"],
            "option_ids": conflict_data.get("option_ids", []), "resolutions": conflict_data["resolutions"]}


def notice(text: str, level: str = "info") -> dict:
    return {"type": "notice", "id": _id(), "level": level, "text": text}


def summary(view: dict, req: Requirements, assumptions: list[str]) -> dict:
    return {
        "type": "summary",
        "id": _id(),
        "model_id": view["model_id"],
        "model_name": view["model_name"],
        "lines": view["lines"],
        "base_price": view["base_price"],
        "options_price": view["options_price"],
        "total_price": view["total_price"],
        "budget": view["budget"],
        "valid": view["valid"],
        "issues": view["issues"],
        "unmet_requirements": [v["message"] for v in view["unmet_requirements"]],
        "specs": view["specs"],
        "requirements": [label for _, label in req.describe()],
        "assumptions": assumptions,
        "powertrain_label": words("powertrain")[view["specs"]["powertrain"]],
    }
