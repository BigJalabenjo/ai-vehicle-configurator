"""Builders for adaptive UI components.

The LLM decides *which* component to show; these builders fill them with
authoritative data from the catalog service, so prices, specs and validity on
screen never come from model-generated text.
"""

from __future__ import annotations

import uuid

from .domain import POWERTRAIN_LABEL, Requirements

POWERTRAIN_SHORT = {"bev": "Electric", "phev": "Plug-in hybrid", "petrol": "Petrol", "diesel": "Diesel"}


def _id() -> str:
    return uuid.uuid4().hex[:8]


def question(prompt: str, choices: list[str], topic: str = "", allow_free_text: bool = True) -> dict:
    return {"type": "question", "id": _id(), "topic": topic, "prompt": prompt,
            "choices": [{"label": c} for c in choices][:6], "allow_free_text": allow_free_text}


def slider(req: Requirements, prompt: str = "What matters more to you on the road?") -> dict:
    return {"type": "slider", "id": _id(), "preference": "sportiness", "prompt": prompt,
            "left_label": "Comfort", "right_label": "Sporty",
            "value": req.sportiness if req.sportiness is not None else 0.5}


def model_card(ev: dict) -> dict:
    s = ev["specs"]
    return {
        "model_id": ev["model_id"],
        "name": ev["name"],
        "powertrain": POWERTRAIN_SHORT[ev["powertrain"]],
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
        out.append(f"{s['electric_range_km']} km range")
    elif s.get("electric_range_km"):
        out.append(f"{s['electric_range_km']} km electric · {s['total_range_km']:,} km total")
    else:
        out.append(f"{s['total_range_km']:,} km range")
    out.append(f"{s['seats']} seats")
    out.append(f"{s['trunk_l']} l boot")
    if s.get("max_tow_kg"):
        out.append(f"tows {s['max_tow_kg']:,} kg")
    return out


def model_cards(evaluations: list[dict], title: str = "Recommended for you") -> dict:
    return {"type": "model_cards", "id": _id(), "title": title, "cards": [model_card(e) for e in evaluations]}


def comparison(evaluations: list[dict]) -> dict:
    rows_spec = [
        ("Price as needed", lambda e: e["entry_price"], "min", lambda v: f"€{v:,}"),
        ("Powertrain", lambda e: POWERTRAIN_SHORT[e["powertrain"]], None, str),
        ("Electric range", lambda e: e["specs"]["electric_range_km"] or 0, "max", lambda v: f"{v} km" if v else "—"),
        ("Total range", lambda e: e["specs"]["total_range_km"], "max", lambda v: f"{v:,} km"),
        ("DC charging", lambda e: e["specs"]["dc_charge_kw"] or 0, "max", lambda v: f"{v} kW" if v else "—"),
        ("Seats", lambda e: e["specs"]["seats"], "max", str),
        ("3 child seats in rear", lambda e: e["specs"]["rear_three_child_seats"], None, lambda v: "Yes" if v else "No"),
        ("Boot", lambda e: e["specs"]["trunk_l"], "max", lambda v: f"{v} l"),
        ("Towing", lambda e: e["specs"]["max_tow_kg"], "max", lambda v: f"{v:,} kg" if v else "—"),
        ("0–100 km/h", lambda e: e["specs"]["acceleration_s"], "min", lambda v: f"{v} s"),
        ("Meets your needs", lambda e: e["fits"], None, lambda v: "Yes" if v else "Not fully"),
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


def tradeoffs(items: list[dict], title: str = "Possible trade-offs") -> dict:
    return {"type": "tradeoffs", "id": _id(), "title": title,
            "items": [{"label": t["label"], "description": t["description"], "model_id": t["model_id"],
                       "patch": t["relax_patch"]} for t in items]}


def option_toggles(view: dict, option_ids: list[str] | None = None, title: str = "Suggested options") -> dict:
    by_id = {o["id"]: o for o in view["catalog_options"]}
    if option_ids is None:
        option_ids = [o["id"] for o in view["catalog_options"] if o["recommended"]]
    options = [by_id[i] for i in option_ids if i in by_id]
    return {"type": "option_toggles", "id": _id(), "title": title, "model_id": view["model_id"], "options": options}


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
        "powertrain_label": POWERTRAIN_LABEL[view["specs"]["powertrain"]],
    }
