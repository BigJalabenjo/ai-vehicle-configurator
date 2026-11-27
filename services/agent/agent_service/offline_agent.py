"""Deterministic "guided mode" agent.

Used when no Anthropic credentials are configured, and as the fallback when
the LLM is unavailable. It uses exactly the same tools and UI components as
the LLM agent, with a fixed dialogue policy:

1. Understand -> 2. recommend with reasons -> 3. ask the single most useful
missing question -> 4. configure -> 5. summarise.
"""

from __future__ import annotations

from . import ui
from .i18n import eur, lang, words
from .nlu import Parsed, parse
from .toolbox import Toolbox, ToolError

TEXT = {
    "en": {
        "q_budget": ("What's the most you'd like to spend?", ["Up to €60,000", "Up to €75,000", "Up to €90,000", "Flexible budget"]),
        "q_people": ("How many people usually travel with you?", ["Just me / two of us", "4–5 people", "6–7 people"]),
        "q_towing": ("Will you tow anything, e.g. on holidays?", ["No towing", "Bike carrier", "Small trailer (750 kg)", "Caravan (1,500 kg)"]),
        "understood": "Here's what I understood: {x}.",
        "got_it": "Got it - {x}.",
        "no_constraint": "no {field} constraint",
        "within_budget": ", {amount} within budget",
        "still_fits": "Noted. Your {model} still fits everything ({price}{budget}).",
        "no_longer_fits": "With that change, your {model} no longer fits: {unmet}.",
        "saves": "{name} (saves {amount})",
        "removing_helps": " Removing {items} would help.",
        "title_updated": "Models that fit your updated needs",
        "start_again": "\n\nOr start again from one of these, which fit your updated needs:",
        "nothing_fits_now": "\n\nNo model meets all your needs as they stand - here's what would make it work:",
        "best_match": "{intro}\n\nBest match: **{name}** from {price}. {reasons}.",
        "others_added": " I've added the other good fits for comparison.",
        "none_at_once": "{intro}\n\nNo model meets all of these at once. Below are the closest matches and the single "
                        "compromise each would need - pick the one that matters least to you.",
        "last_slider": "Last thing: comfort or sportiness?",
        "closest": "Closest matches",
        "worth_considering": "Worth considering",
        "make_it_work": "What would make it work",
        "great_choice": "Great choice - let's configure the **{model}**.",
        "current_price": " Current price: {price}",
        "left_in_budget": " ({amount} left in your budget).",
        "note": " Note: {x}.",
        "toggles_title": "Suggested for how you'll use it",
        "worth_a_look": "\n\nBased on what you told me, these options are worth a look:",
        "not_possible": "That's not possible: {error}",
        "clashes": "That clashes with your current configuration - choose how to resolve it:",
        "done": "Done.",
        "new_total": " New total: {price}",
        "over_budget": " - {amount} over your budget.",
        "saving_item": "{name} (−{amount})",
        "could_remove": " You could remove {items}.",
        "left": " ({amount} left).",
        "compare": "Here's a side-by-side view. Against your needs, the **{name}** comes out ahead.",
        "summary_ok": "Your {model} is fully valid at {price}. Here's the summary with the reasoning behind each choice.",
        "summary_attention": "Here's your summary - a few points still need attention: {x}",
        "next_prompt": ("What would you like to do next?", ["Show me a summary", "Compare with alternatives", "Show other models"]),
        "didnt_catch": "I didn't quite catch that. You can toggle options on the right, or tell me what you'd like to change.",
        "usage_prompt": ("Tell me a bit about how you'll use the car:", ["Family car for long trips", "Mostly city driving", "Something sporty"]),
        "no_requirements": "I didn't catch any requirements there. Try something like: \"family car, electric, three kids, "
                           "budget €85,000\".",
        "or": " or ",
    },
    "de": {
        "q_budget": ("Wie viel möchten Sie höchstens ausgeben?", ["Bis 60.000 €", "Bis 75.000 €", "Bis 90.000 €", "Budget ist flexibel"]),
        "q_people": ("Wie viele Personen fahren normalerweise mit?", ["Nur ich / zu zweit", "4–5 Personen", "6–7 Personen"]),
        "q_towing": ("Ziehen Sie etwas, z. B. im Urlaub?", ["Nichts ziehen", "Fahrradträger", "Kleiner Anhänger (750 kg)", "Wohnwagen (1.500 kg)"]),
        "understood": "Das habe ich verstanden: {x}.",
        "got_it": "Alles klar – {x}.",
        "no_constraint": "keine Vorgabe mehr für {field}",
        "within_budget": ", {amount} unter Budget",
        "still_fits": "Notiert. Ihr {model} passt weiterhin zu allem ({price}{budget}).",
        "no_longer_fits": "Mit dieser Änderung passt Ihr {model} nicht mehr: {unmet}.",
        "saves": "{name} (spart {amount})",
        "removing_helps": " Es würde helfen, {items} zu entfernen.",
        "title_updated": "Modelle, die zu Ihren neuen Anforderungen passen",
        "start_again": "\n\nOder starten Sie neu mit einem dieser Modelle, die zu Ihren neuen Anforderungen passen:",
        "nothing_fits_now": "\n\nKein Modell erfüllt Ihre Anforderungen in dieser Form – so könnte es klappen:",
        "best_match": "{intro}\n\nAm besten passt der **{name}** ab {price}. {reasons}.",
        "others_added": " Die anderen passenden Modelle habe ich zum Vergleich dazugestellt.",
        "none_at_once": "{intro}\n\nKein Modell erfüllt all das gleichzeitig. Unten sehen Sie die nächstliegenden Modelle "
                        "und den einen Kompromiss, den jedes bräuchte – wählen Sie den, der Ihnen am wenigsten wichtig ist.",
        "last_slider": "Zum Schluss: eher Komfort oder eher sportlich?",
        "closest": "Am nächsten dran",
        "worth_considering": "Eine Überlegung wert",
        "make_it_work": "So könnte es passen",
        "great_choice": "Gute Wahl – konfigurieren wir den **{model}**.",
        "current_price": " Aktueller Preis: {price}",
        "left_in_budget": " ({amount} unter Ihrem Budget).",
        "note": " Hinweis: {x}.",
        "toggles_title": "Passend zu Ihrer Nutzung",
        "worth_a_look": "\n\nNach dem, was Sie mir erzählt haben, lohnt sich ein Blick auf diese Optionen:",
        "not_possible": "Das geht leider nicht: {error}",
        "clashes": "Das passt nicht zu Ihrer aktuellen Konfiguration – wählen Sie, wie es weitergehen soll:",
        "done": "Erledigt.",
        "new_total": " Neuer Gesamtpreis: {price}",
        "over_budget": " – {amount} über Ihrem Budget.",
        "saving_item": "{name} (−{amount})",
        "could_remove": " Sie könnten {items} entfernen.",
        "left": " (noch {amount} Spielraum).",
        "compare": "Hier der direkte Vergleich. Gemessen an Ihren Anforderungen liegt der **{name}** vorn.",
        "summary_ok": "Ihr {model} ist für {price} vollständig gültig. Hier ist die Zusammenfassung mit der Begründung für jede Wahl.",
        "summary_attention": "Hier ist Ihre Zusammenfassung – ein paar Punkte brauchen noch Aufmerksamkeit: {x}",
        "next_prompt": ("Wie möchten Sie weitermachen?", ["Zusammenfassung zeigen", "Mit Alternativen vergleichen", "Andere Modelle zeigen"]),
        "didnt_catch": "Das habe ich nicht ganz verstanden. Sie können rechts Optionen an- und abwählen oder mir sagen, was Sie ändern möchten.",
        "usage_prompt": ("Erzählen Sie mir kurz, wie Sie das Auto nutzen:", ["Familienauto für lange Strecken", "Vor allem Stadtverkehr", "Etwas Sportliches"]),
        "no_requirements": "Darin habe ich keine Anforderungen erkannt. Versuchen Sie es etwa so: „Familienauto, elektrisch, "
                           "drei Kinder, Budget 85.000 €“.",
        "or": " oder ",
    },
}


def _t(key: str, **kw):
    value = TEXT[lang()][key]
    return value.format(**kw) if isinstance(value, str) else value


QUESTIONS = [
    ("budget", lambda r: r.budget_max is None, "q_budget"),
    ("people", lambda r: r.min_seats is None and r.child_seats is None, "q_people"),
    ("towing", lambda r: r.towing_kg is None and (bool(r.child_seats) or r.long_distance), "q_towing"),
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
        intro = _t("understood", x=understood) if understood else ""
        if state.turns > 0 and p is not None and p.patch:
            changed = [label for f, label in state.requirements.describe() if f in p.patch]
            cleared = [words("field").get(f, f.replace("_", " ")) for f, v in p.patch.items() if v is None]
            parts = changed + [_t("no_constraint", field=c) for c in cleared]
            intro = _t("got_it", x="; ".join(parts)) if parts else intro

        if state.model_id and not (p and p.wants_alternatives):
            view = await tb.current_view()
            unmet = [v["message"] for v in view["unmet_requirements"]]
            if not unmet:
                b = view["budget"]
                budget = _t("within_budget", amount=eur(b["remaining"])) if b["max"] is not None else ""
                return _t("still_fits", model=view["model_name"], price=eur(view["total_price"]), budget=budget)
            res = await tb.search_models()
            text = _t("no_longer_fits", model=view["model_name"], unmet="; ".join(unmet))
            if view["savings"]:
                items = _t("or").join(_t("saves", name=s["name"], amount=eur(s["saves"])) for s in view["savings"][:2])
                text += _t("removing_helps", items=items)
            self._show_results(tb, res, title=_t("title_updated"))
            return text + (_t("start_again") if res["fits"] else _t("nothing_fits_now"))

        res = await tb.search_models()
        if res["fits"]:
            top = res["fits"][0]
            text = _t("best_match", intro=intro, name=top["name"], price=eur(top["entry_price"]),
                      reasons=". ".join(top["reasons"][:2]))
            if len(res["fits"]) > 1:
                text += _t("others_added")
        else:
            text = _t("none_at_once", intro=intro)
        self._show_results(tb, res)
        q = self._next_question(tb)
        if q:
            tb.components.append(q)
        elif tb.state.requirements.sportiness is None and "sportiness" not in tb.state.asked:
            tb.state.asked.append("sportiness")
            tb.components.append(ui.slider(tb.state.requirements, _t("last_slider")))
        return text.strip()

    def _show_results(self, tb: Toolbox, res: dict, title: str | None = None) -> None:
        fits = [tb.state.evaluations[e["model_id"]] for e in res["fits"]]
        near = [tb.state.evaluations[e["model_id"]] for e in res["near_misses"]]
        if fits:
            tb.components.append(ui.model_cards(fits, title))
        elif near:
            tb.components.append(ui.model_cards(near, _t("closest")))
        if res["tradeoffs"]:
            tb.components.append(ui.tradeoffs(tb.state.last_tradeoffs,
                                              _t("worth_considering") if fits else _t("make_it_work")))

    def _next_question(self, tb: Toolbox) -> dict | None:
        req, asked = tb.state.requirements, tb.state.asked
        for topic, needed, key in QUESTIONS:
            if topic not in asked and needed(req):
                asked.append(topic)
                prompt, choices = _t(key)
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
        text = _t("great_choice", model=res["model"])
        if res["notes"]:
            text += " " + " ".join(res["notes"])
        b = view["budget"]
        text += _t("current_price", price=eur(view["total_price"]))
        text += _t("left_in_budget", amount=eur(b["remaining"])) if b["max"] is not None and b["remaining"] >= 0 else "."
        if view["unmet_requirements"]:
            text += _t("note", x="; ".join(v["message"] for v in view["unmet_requirements"]))
        toggles = ui.option_toggles(view, title=_t("toggles_title"))
        if toggles["options"]:
            tb.components.append(toggles)
            text += _t("worth_a_look")
        return text

    async def change(self, tb: Toolbox, action: str, option_id: str, force: bool = False) -> str:
        try:
            res = await tb.change_option(action, option_id, force)
        except ToolError as exc:
            return str(exc)
        if res["status"] == "rejected":
            return _t("not_possible", error=res["error"])
        if res["status"] == "conflict":
            return _t("clashes")
        if res["status"] == "noop":
            return " ".join(res["notes"])
        text = " ".join(res["notes"]) or _t("done")
        b = res["budget"]
        text += _t("new_total", price=eur(res["total_price"]))
        if b["max"] is not None:
            if b["over_by"]:
                text += _t("over_budget", amount=eur(b["over_by"]))
                savings = res.get("savings_if_over_budget") or []
                if savings:
                    items = _t("or").join(_t("saving_item", name=s["name"], amount=eur(s["saves"])) for s in savings[:2])
                    text += _t("could_remove", items=items)
            else:
                text += _t("left", amount=eur(b["remaining"]))
        else:
            text += "."
        return text

    async def compare(self, tb: Toolbox, model_ids: list[str]) -> str:
        await tb.compare_models(model_ids)
        evs = [tb.state.evaluations[m] for m in model_ids if m in tb.state.evaluations]
        tb.components.append(ui.comparison(evs))
        best = max(evs, key=lambda e: (e["fits"], e["score"]))
        return _t("compare", name=best["name"])

    async def summary(self, tb: Toolbox) -> str:
        view = await tb.current_view()
        tb.components.append(ui.summary(view, tb.state.requirements, tb.state.assumptions))
        if view["valid"] and not view["unmet_requirements"]:
            return _t("summary_ok", model=view["model_name"], price=eur(view["total_price"]))
        return _t("summary_attention", x="; ".join(
            [i["message"] for i in view["issues"]] + [v["message"] for v in view["unmet_requirements"]]))

    async def _top_ids(self, tb: Toolbox, n: int) -> list[str]:
        res = await tb.search_models(limit=n)
        return [e["model_id"] for e in (res["fits"] + res["near_misses"])][:n]

    def clarify(self, tb: Toolbox) -> str:
        if tb.state.model_id:
            tb.components.append(ui.question(*_t("next_prompt")))
            return _t("didnt_catch")
        tb.components.append(ui.question(*_t("usage_prompt")))
        return _t("no_requirements")
