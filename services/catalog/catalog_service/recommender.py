"""Requirement matching, ranking and trade-off generation.

Hard requirements filter models; soft preferences rank them. Every score
contribution is paired with a human-readable reason so the agent (and the UI)
can explain *why* a model is suggested. When a model misses requirements, each
violation carries the requirements patch that would relax it - this powers the
trade-off cards in the UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import i18n
from .i18n import eur, num, t
from .schemas import ModelEvaluation, RecommendResponse, Requirements, Tradeoff, VehicleModel, Violation

if TYPE_CHECKING:
    from .rules import ConfigurationEngine

LONG_DISTANCE_MIN_RANGE_KM = 450



def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def required_seat_count(req: Requirements) -> int | None:
    needs = [n for n in (req.min_seats, (req.child_seats + 1) if req.child_seats else None) if n]
    return max(needs) if needs else None


def options_needed_for(engine: "ConfigurationEngine", model: VehicleModel, req: Requirements) -> list[str]:
    """Options that must be added to this model to satisfy capability requirements."""
    needed: list[str] = []
    if req.towing_kg is not None and 0 < model.tow_kg and req.towing_kg <= model.tow_kg:
        if engine.is_available("tow_hitch", model):
            needed.append("tow_hitch")
    seats = required_seat_count(req)
    third_row_helps = (seats and seats > model.seats) or (
        (req.child_seats or 0) >= 3 and not model.rear_three_child_seats
    )
    if third_row_helps and "third_row" in engine.repo.options and engine.is_available("third_row", model):
        needed.append("third_row")
    for oid in req.must_have_options:
        if oid in engine.repo.options and engine.is_available(oid, model) and oid not in needed:
            needed.append(oid)
    return needed


def requirement_violations(
    engine: "ConfigurationEngine", model: VehicleModel, options: list[str], req: Requirements
) -> list[Violation]:
    """Which requirements does this concrete configuration fail, and how could each be relaxed?"""
    specs = engine.specs(model, options)
    total = engine.price_of(model, options)
    locked = engine.included_by(options)
    out: list[Violation] = []

    if req.body_styles and model.body not in req.body_styles:
        out.append(Violation(code="body", message=t("v_body", body=i18n.body(model.body)),
                             relax_patch={"body_styles": []}, relax_label=t("v_body_relax")))
    if req.powertrain_required and model.powertrain not in req.powertrain_required:
        out.append(Violation(
            code="powertrain", message=t("v_powertrain", has=i18n.powertrain(model.powertrain),
                                         wanted=" / ".join(i18n.powertrain(p, inline=True) for p in req.powertrain_required)),
            relax_patch={"powertrain_required": [], "powertrain_preferred": list(req.powertrain_required)},
            relax_label=t("v_powertrain_relax", pt=i18n.powertrain(model.powertrain, inline=True)),
        ))
    seats = required_seat_count(req)
    if seats and specs["seats"] < seats:
        out.append(Violation(code="seats", message=t("v_seats", seats=specs["seats"], need=seats),
                             relax_patch={"min_seats": specs["seats"]}, relax_label=t("v_seats_relax", seats=specs["seats"])))
    if (req.child_seats or 0) >= 3 and not model.rear_three_child_seats and specs["seats"] < 7:
        out.append(Violation(code="child_seats", message=t("v_child_seats"),
                             relax_patch={"child_seats": 2}, relax_label=t("v_child_seats_relax")))
    if req.towing_kg is not None:
        if model.tow_kg == 0:
            out.append(Violation(code="towing", message=t("v_no_hitch"),
                                 relax_patch={"towing_kg": None}, relax_label=t("v_skip_towing")))
        elif req.towing_kg > model.tow_kg:
            out.append(Violation(code="towing", message=t("v_tow_max", max=num(model.tow_kg), need=num(req.towing_kg)),
                                 relax_patch={"towing_kg": model.tow_kg}, relax_label=t("v_tow_relax", max=num(model.tow_kg))))
        elif "tow_hitch" not in options:
            out.append(Violation(code="towing", message=t("v_hitch_missing"),
                                 relax_patch={"towing_kg": None}, relax_label=t("v_skip_towing")))
    if req.long_distance and model.powertrain == "bev" and (specs["electric_range_km"] or 0) < LONG_DISTANCE_MIN_RANGE_KM:
        out.append(Violation(
            code="range",
            message=t("v_range", range=specs["electric_range_km"], min=LONG_DISTANCE_MIN_RANGE_KM),
            relax_patch={"long_distance": False}, relax_label=t("v_range_relax", range=specs["electric_range_km"]),
        ))
    if req.min_trunk_l and specs["trunk_l"] < req.min_trunk_l:
        out.append(Violation(code="trunk", message=t("v_trunk", trunk=specs["trunk_l"], need=req.min_trunk_l),
                             relax_patch={"min_trunk_l": specs["trunk_l"]}, relax_label=t("v_trunk_relax", trunk=specs["trunk_l"])))
    for oid in req.must_have_options:
        if oid not in engine.repo.options:
            continue
        name = engine.repo.options[oid].name
        others = [o for o in req.must_have_options if o != oid]
        if not engine.is_available(oid, model):
            out.append(Violation(code="option_unavailable", message=t("v_option_not_offered", name=name),
                                 relax_patch={"must_have_options": others}, relax_label=t("v_option_relax", name=name)))
        elif oid not in options and oid not in locked:
            out.append(Violation(code="option_unavailable", message=t("v_option_not_added", name=name),
                                 relax_patch={"must_have_options": others}, relax_label=t("v_option_relax", name=name)))
    if req.budget_max is not None and total > req.budget_max:
        out.append(Violation(code="budget", message=t("v_budget", total=eur(total), over=eur(total - req.budget_max),
                                                      budget=eur(req.budget_max)),
                             relax_patch={"budget_max": total}, relax_label=t("v_budget_relax", total=eur(total))))
    return out


def evaluate(engine: "ConfigurationEngine", model: VehicleModel, req: Requirements) -> ModelEvaluation:
    needed = options_needed_for(engine, model, req)
    options, _problems = engine.entry_configuration(model, needed)
    violations = requirement_violations(engine, model, options, req)
    specs = engine.specs(model, options)
    entry_price = engine.price_of(model, options)

    score = 50.0
    reasons: list[str] = []
    pref = req.powertrain_preferred
    if pref:
        if model.powertrain in pref:
            score += 20
            reasons.append(t("r_preferred", pt=i18n.powertrain(model.powertrain)))
        elif "bev" in pref and model.powertrain == "phev":
            score += 6
            reasons.append(t("r_phev", km=model.electric_range_km))
        else:
            score -= 8
    if req.long_distance:
        if model.powertrain == "bev":
            rng = specs["electric_range_km"] or 0
            score += _clamp((rng - LONG_DISTANCE_MIN_RANGE_KM) / 15, 0, 10) + _clamp((model.dc_charge_kw or 0) / 40, 0, 5)
            reasons.append(t("r_bev_long", range=rng, kw=model.dc_charge_kw))
        else:
            score += 8
            reasons.append(t("r_ice_long", km=num(specs["total_range_km"])))
    if (req.child_seats or 0) >= 3 and model.rear_three_child_seats:
        score += 5
        reasons.append(t("r_three_child_seats"))
    if req.child_seats or (req.min_seats or 0) >= 5:
        score += _clamp((specs["trunk_l"] - 450) / 30, 0, 5)
        if specs["trunk_l"] >= 550:
            reasons.append(t("r_boot", trunk=specs["trunk_l"]))
    if req.sportiness is not None:
        fit = req.sportiness * model.sport + (1 - req.sportiness) * model.comfort
        score += fit * 10
        if fit >= 0.75:
            reasons.append(t("r_sporty") if req.sportiness >= 0.5 else t("r_comfort"))
    if req.towing_kg is not None and model.tow_kg >= (req.towing_kg or 0) > 0:
        reasons.append(t("r_tows", kg=num(model.tow_kg)))
    if req.budget_max is not None and entry_price <= req.budget_max:
        headroom = req.budget_max - entry_price
        score += _clamp(headroom / 2000, 0, 8)
        reasons.append(t("r_budget", price=eur(entry_price), headroom=eur(headroom)))
    if not reasons:
        reasons.append(model.summary)

    return ModelEvaluation(
        model_id=model.id,
        name=model.name,
        body=model.body,
        powertrain=model.powertrain,
        base_price=model.base_price,
        entry_price=entry_price,
        required_options=[o for o in needed],
        fits=not violations,
        score=round(min(score, 100), 1),
        reasons=reasons,
        violations=violations,
        specs=specs,
    )


def recommend(
    engine: "ConfigurationEngine", req: Requirements, model_ids: list[str] | None = None, limit: int = 3
) -> RecommendResponse:
    models = [engine.model(mid) for mid in model_ids] if model_ids else list(engine.repo.models.values())
    evaluations = [evaluate(engine, m, req) for m in models]
    fits = sorted((e for e in evaluations if e.fits), key=lambda e: -e.score)
    misses = sorted(
        (e for e in evaluations if not e.fits),
        key=lambda e: (len(e.violations), _overshoot(e, req), -e.score),
    )
    if model_ids:  # explicit comparison: return everything requested
        return RecommendResponse(fits=fits, near_misses=misses, tradeoffs=_tradeoffs(misses, req),
                                 explanation=_explain(fits, misses))
    near = [e for e in misses if len(e.violations) <= 2][:limit]
    return RecommendResponse(
        fits=fits[:limit], near_misses=near, tradeoffs=_tradeoffs(near, req), explanation=_explain(fits, near)
    )


def _overshoot(e: ModelEvaluation, req: Requirements) -> int:
    return max(0, e.entry_price - req.budget_max) if req.budget_max is not None else 0


def _tradeoffs(misses: list[ModelEvaluation], req: Requirements) -> list[Tradeoff]:
    out: list[Tradeoff] = []
    seen: set[str] = set()
    for e in misses[:4]:
        if len(e.violations) > 2:
            continue
        patch: dict = {}
        for v in e.violations:
            patch.update(v.relax_patch)
        key = repr(sorted(patch.items()))
        if key in seen:  # same compromise already offered for a better-ranked model
            continue
        seen.add(key)
        label = " + ".join(v.relax_label for v in e.violations)
        gains = e.reasons[0] if e.reasons else ""
        out.append(Tradeoff(
            label=label,
            description=t("tradeoff", name=e.name, violations="; ".join(v.message for v in e.violations), gains=gains).strip(),
            model_id=e.model_id,
            relax_patch=patch,
        ))
    return out


def _explain(fits: list[ModelEvaluation], near: list[ModelEvaluation]) -> str:
    if fits:
        msg = t("explain_fits", n=len(fits))
        if near:
            msg += t("explain_more", n=len(near))
        return msg + "."
    if near:
        return t("explain_near")
    return t("explain_none")


def option_recommendations(
    engine: "ConfigurationEngine", model: VehicleModel, options: list[str], req: Requirements
) -> dict[str, str]:
    wanted: list[tuple[str, str]] = []
    if req.long_distance:
        wanted.append(("long_distance", t("o_long_distance")))
    if req.child_seats or (req.min_seats or 0) >= 5:
        wanted.append(("family", t("o_family")))
    if req.sportiness is not None and req.sportiness >= 0.65:
        wanted.append(("sport", t("o_sport")))
    if req.sportiness is not None and req.sportiness <= 0.35:
        wanted.append(("comfort", t("o_comfort")))
    locked = engine.included_by(options)
    locked_groups = {engine.repo.options[o].group for o in locked if engine.repo.options[o].group}
    chosen_groups = {engine.repo.options[o].group for o in options
                     if engine.repo.options[o].group and o not in model.standard_options}
    recs: dict[str, str] = {}
    covered: set[str] = set()  # options (and groups) already covered by a recommended package
    candidates = sorted(engine.repo.options.values(), key=lambda o: (0 if o.includes else 1, -o.price))
    for tag, reason in wanted:
        picked = 0
        for opt in candidates:
            if picked >= 3:
                break
            if opt.id in options or opt.id in locked or opt.id in recs or opt.id in covered:
                continue
            if not engine.is_available(opt.id, model) or tag not in opt.tags:
                continue
            if opt.group and (opt.group in locked_groups or opt.group in chosen_groups or opt.group in covered):
                continue
            if any(inc in locked for inc in opt.includes):
                continue
            if any(x in options for x in opt.excludes) or any(opt.id in engine.repo.options[x].excludes for x in options):
                continue
            recs[opt.id] = reason
            picked += 1
            for inc in opt.includes:
                covered.add(inc)
                if engine.repo.options[inc].group:
                    covered.add(engine.repo.options[inc].group)
    if req.towing_kg is not None and "tow_hitch" not in options and engine.is_available("tow_hitch", model):
        recs["tow_hitch"] = t("o_towing")
    return dict(list(recs.items())[:6])




def selection_reason(engine: "ConfigurationEngine", model: VehicleModel, option_id: str, req: Requirements) -> str:
    """Why a customer-selected option makes sense, in terms of their stated needs (for the summary)."""
    if option_id in options_needed_for(engine, model, req):
        # The hitch can be needed for a towing weight, or simply be a must-have without one.
        if option_id == "tow_hitch" and req.towing_kg is not None:
            return t("s_bike_carrier") if req.towing_kg == 0 else t("s_tow", kg=num(req.towing_kg))
        if option_id == "third_row":
            return t("s_seats")
        return t("s_asked")
    tags = engine.repo.options[option_id].tags
    if req.long_distance and "long_distance" in tags:
        return t("s_long_distance")
    if (req.child_seats or (req.min_seats or 0) >= 5) and "family" in tags:
        return t("o_family")
    if req.sportiness is not None and req.sportiness >= 0.65 and "sport" in tags:
        return t("o_sport")
    return t("s_choice")
