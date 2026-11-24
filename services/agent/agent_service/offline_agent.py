"""Deterministic "guided mode" agent.

Used when no Anthropic credentials are configured, and as the fallback when
the LLM is unavailable. It uses exactly the same tools and UI components as
the Claude agent, with a fixed dialogue policy:

1. Understand -> 2. recommend with reasons -> 3. ask the single most useful
missing question -> 4. configure -> 5. summarise.
"""

from __future__ import annotations

from . import ui
from .nlu import Parsed, parse
from .toolbox import Toolbox, ToolError


def eur(v: int) -> str:
    return f"€{v:,}"


QUESTIONS = [
    ("budget", lambda r: r.budget_max is None,
     "What's the most you'd like to spend?", ["Up to €60,000", "Up to €75,000", "Up to €90,000", "Flexible budget"]),
    ("people", lambda r: r.min_seats is None and r.child_seats is None,
     "How many people usually travel with you?", ["Just me / two of us", "4–5 people", "6–7 people"]),
    ("towing", lambda r: r.towing_kg is None and (bool(r.child_seats) or r.long_distance),
     "Will you tow anything, e.g. on holidays?", ["No towing", "Bike carrier", "Small trailer (750 kg)", "Caravan (1,500 kg)"]),
]


class OfflineAgent:
    name = "guided"

    async def run(self, tb: Toolbox, text: str) -> str:
        p = parse(text)
        state = tb.state
        if p.patch:
            await tb.update_requirements(p.patch, p.assumptions)

        if (p.add_options or p.remove_options) and state.model_id and not (p.model_ids and p.wants_select):
            parts = []
            for oid in p.add_options:
                parts.append(await self.change(tb, "add", oid))
            for oid in p.remove_options:
                parts.append(await self.change(tb, "remove", oid))
            return "\n\n".join(parts)

        if p.wants_compare or len(p.model_ids) >= 2:
            ids = p.model_ids[:3] or await self._top_ids(tb, 2)
            if len(ids) >= 2:
                return await self.compare(tb, ids)

        if p.model_ids and (p.wants_select or not p.patch):
            return await self.select(tb, p.model_ids[0])

        if p.wants_summary and state.model_id:
            return await self.summary(tb)

        if p.patch or p.wants_alternatives or not state.model_id:
            if p.empty and state.turns > 0 and not p.wants_alternatives:
                return self.clarify(tb)
            return await self.recommend(tb, p)
        return self.clarify(tb)

    # ------------------------------------------------------------------ steps

    async def recommend(self, tb: Toolbox, p: Parsed | None = None) -> str:
        state = tb.state
        understood = "; ".join(label for _, label in state.requirements.describe())
        intro = f"Here's what I understood: {understood}." if understood else ""
        if state.turns > 0 and p is not None and p.patch:
            changed = [label for f, label in state.requirements.describe() if f in p.patch]
            cleared = [f.replace("_", " ") for f, v in p.patch.items() if v is None]
            intro = "Got it - " + "; ".join(changed + [f"no {c} constraint" for c in cleared]) + "." if (changed or cleared) else intro

        if state.model_id and not (p and p.wants_alternatives):
            view = await tb.current_view()
            unmet = [v["message"] for v in view["unmet_requirements"]]
            if not unmet:
                b = view["budget"]
                budget = f", {eur(b['remaining'])} within budget" if b["max"] is not None else ""
                return f"Noted. Your {view['model_name']} still fits everything ({eur(view['total_price'])}{budget})."
            res = await tb.search_models()
            text = (f"With that change, your {view['model_name']} no longer fits: " + "; ".join(unmet) + ".")
            if view["savings"]:
                text += " Removing " + " or ".join(f"{s['name']} (saves {eur(s['saves'])})" for s in view["savings"][:2]) + " would help."
            self._show_results(tb, res, title="Models that fit your updated needs")
            return text + ("\n\nOr start again from one of these, which fit your updated needs:" if res["fits"]
                           else "\n\nNo model meets all your needs as they stand - here's what would make it work:")

        res = await tb.search_models()
        if res["fits"]:
            top = res["fits"][0]
            text = (f"{intro}\n\nBest match: **{top['name']}** from {eur(top['entry_price'])}. "
                    + ". ".join(top["reasons"][:2]) + ".")
            if len(res["fits"]) > 1:
                text += " I've added the other good fits for comparison."
        else:
            text = (f"{intro}\n\nNo model meets all of these at once. "
                    "Below are the closest matches and the single compromise each would need - pick the one that "
                    "matters least to you.")
        self._show_results(tb, res)
        q = self._next_question(tb)
        if q:
            tb.components.append(q)
        elif tb.state.requirements.sportiness is None and "sportiness" not in tb.state.asked:
            tb.state.asked.append("sportiness")
            tb.components.append(ui.slider(tb.state.requirements, "Last thing: comfort or sportiness?"))
        return text.strip()

    def _show_results(self, tb: Toolbox, res: dict, title: str = "Recommended for you") -> None:
        fits = [tb.state.evaluations[e["model_id"]] for e in res["fits"]]
        near = [tb.state.evaluations[e["model_id"]] for e in res["near_misses"]]
        if fits:
            tb.components.append(ui.model_cards(fits, title))
        elif near:
            tb.components.append(ui.model_cards(near, "Closest matches"))
        if res["tradeoffs"]:
            tb.components.append(ui.tradeoffs(tb.state.last_tradeoffs,
                                              "Worth considering" if fits else "What would make it work"))

    def _next_question(self, tb: Toolbox) -> dict | None:
        req, asked = tb.state.requirements, tb.state.asked
        for topic, needed, prompt, choices in QUESTIONS:
            if topic not in asked and needed(req):
                asked.append(topic)
                return ui.question(prompt, choices, topic)
        return None

    async def select(self, tb: Toolbox, model_id: str) -> str:
        try:
            res = await tb.select_model(model_id)
        except ToolError as exc:
            return str(exc)
        return await self.describe_selection(tb, res)

    async def describe_selection(self, tb: Toolbox, res: dict) -> str:
        view = tb.view
        text = f"Great choice - let's configure the **{res['model']}**."
        if res["notes"]:
            text += " " + " ".join(res["notes"])
        b = view["budget"]
        text += f" Current price: {eur(view['total_price'])}"
        text += f" ({eur(b['remaining'])} left in your budget)." if b["max"] is not None and b["remaining"] >= 0 else "."
        if view["unmet_requirements"]:
            text += " Note: " + "; ".join(v["message"] for v in view["unmet_requirements"]) + "."
        toggles = ui.option_toggles(view, title="Suggested for how you'll use it")
        if toggles["options"]:
            tb.components.append(toggles)
            text += "\n\nBased on what you told me, these options are worth a look:"
        return text

    async def change(self, tb: Toolbox, action: str, option_id: str, force: bool = False) -> str:
        try:
            res = await tb.change_option(action, option_id, force)
        except ToolError as exc:
            return str(exc)
        if res["status"] == "rejected":
            return f"That's not possible: {res['error']}"
        if res["status"] == "conflict":
            return "That clashes with your current configuration - choose how to resolve it:"
        if res["status"] == "noop":
            return " ".join(res["notes"])
        text = " ".join(res["notes"]) or "Done."
        b = res["budget"]
        text += f" New total: {eur(res['total_price'])}"
        if b["max"] is not None:
            if b["over_by"]:
                text += f" - {eur(b['over_by'])} over your budget."
                savings = res.get("savings_if_over_budget") or []
                if savings:
                    text += " You could remove " + " or ".join(f"{s['name']} (−{eur(s['saves'])})" for s in savings[:2]) + "."
            else:
                text += f" ({eur(b['remaining'])} left)."
        else:
            text += "."
        return text

    async def compare(self, tb: Toolbox, model_ids: list[str]) -> str:
        await tb.compare_models(model_ids)
        evs = [tb.state.evaluations[m] for m in model_ids if m in tb.state.evaluations]
        tb.components.append(ui.comparison(evs))
        best = max(evs, key=lambda e: (e["fits"], e["score"]))
        return f"Here's a side-by-side view. Against your needs, the **{best['name']}** comes out ahead."

    async def summary(self, tb: Toolbox) -> str:
        view = await tb.current_view()
        tb.components.append(ui.summary(view, tb.state.requirements, tb.state.assumptions))
        if view["valid"] and not view["unmet_requirements"]:
            return (f"Your {view['model_name']} is fully valid at {eur(view['total_price'])}. Here's the summary with "
                    "the reasoning behind each choice.")
        return "Here's your summary - a few points still need attention: " + "; ".join(
            [i["message"] for i in view["issues"]] + [v["message"] for v in view["unmet_requirements"]])

    async def _top_ids(self, tb: Toolbox, n: int) -> list[str]:
        res = await tb.search_models(limit=n)
        return [e["model_id"] for e in (res["fits"] + res["near_misses"])][:n]

    def clarify(self, tb: Toolbox) -> str:
        if tb.state.model_id:
            tb.components.append(ui.question("What would you like to do next?",
                                             ["Show me a summary", "Compare with alternatives", "Show other models"]))
            return "I didn't quite catch that. You can toggle options on the right, or tell me what you'd like to change."
        tb.components.append(ui.question("Tell me a bit about how you'll use the car:",
                                         ["Family car for long trips", "Mostly city driving", "Something sporty"]))
        return ("I didn't catch any requirements there. Try something like: \"family car, electric, three kids, "
                "budget €85,000\".")
