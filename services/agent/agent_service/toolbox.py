"""Configurator tools shared by the Claude agent and the offline agent.

Each tool mutates the session state only through the catalog service and
returns a compact, JSON-able result for the model. UI components produced
during a turn are collected in ``Toolbox.components``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from . import ui
from .catalog_client import CatalogClient, CatalogError
from .domain import Requirements
from .state import SessionState


class ToolError(Exception):
    """Recoverable tool failure; the message is shown to the model so it can correct itself."""


# --------------------------------------------------------------------------- tool inputs


class UpdateRequirementsInput(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = []


class SearchInput(BaseModel):
    limit: int = Field(default=3, ge=1, le=5)


class CompareInput(BaseModel):
    model_ids: list[str] = Field(min_length=2, max_length=3)


class SelectModelInput(BaseModel):
    model_id: str


class ChangeOptionInput(BaseModel):
    action: Literal["add", "remove"]
    option_id: str
    force: bool = False


class UIComponentSpec(BaseModel):
    type: Literal["question", "preference_slider", "model_cards", "comparison", "tradeoffs", "option_toggles", "summary"]
    prompt: str | None = None
    choices: list[str] = []
    topic: str | None = None
    model_ids: list[str] = []
    option_ids: list[str] = []
    title: str | None = None


class ShowUIInput(BaseModel):
    components: list[UIComponentSpec] = Field(min_length=1, max_length=3)


REQUIREMENT_SCHEMA = {
    "type": "object",
    "description": "Only include fields that changed. Set a field to null to clear it.",
    "properties": {
        "budget_max": {"type": ["integer", "null"], "description": "Max total price in EUR"},
        "powertrain_preferred": {"type": ["array", "null"], "items": {"enum": ["bev", "phev", "petrol", "diesel"]},
                                 "description": "Soft preference, e.g. 'I prefer electric' -> ['bev']"},
        "powertrain_required": {"type": ["array", "null"], "items": {"enum": ["bev", "phev", "petrol", "diesel"]},
                                "description": "Hard constraint, only when the customer insists ('must be electric')"},
        "min_seats": {"type": ["integer", "null"]},
        "child_seats": {"type": ["integer", "null"], "description": "Number of child seats needed"},
        "long_distance": {"type": ["boolean", "null"], "description": "Regular long trips (>300 km)"},
        "towing_kg": {"type": ["integer", "null"], "description": "Trailer weight in kg; 0 = bike carrier only"},
        "min_trunk_l": {"type": ["integer", "null"]},
        "body_styles": {"type": ["array", "null"], "items": {"enum": ["gran_coupe", "touring", "sav", "tourer", "sedan"]}},
        "sportiness": {"type": ["number", "null"], "description": "0 = comfort focus, 1 = sporty"},
        "must_have_options": {"type": ["array", "null"], "items": {"type": "string"}, "description": "Option ids"},
    },
    "additionalProperties": False,
}

TOOLS: list[dict] = [
    {
        "name": "update_requirements",
        "description": "Record or revise the customer's needs. Call whenever the customer states or changes a need, "
                       "including revisions ('actually my budget is 75k'). Returns the merged requirements and, if a "
                       "model is selected, whether the current configuration still satisfies them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": REQUIREMENT_SCHEMA,
                "assumptions": {"type": "array", "items": {"type": "string"},
                                "description": "Interpretations you made that the customer should be able to correct, "
                                               "e.g. 'Three children -> three child seats in the rear row'"},
            },
            "required": ["patch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_models",
        "description": "Rank catalog models against the current requirements. Returns models that fit, near misses with "
                       "the exact violated requirement, and trade-offs (requirement relaxations that would make a model fit).",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 5}},
                         "additionalProperties": False},
    },
    {
        "name": "compare_models",
        "description": "Side-by-side evaluation of 2-3 models against the current requirements.",
        "input_schema": {"type": "object", "properties": {"model_ids": {"type": "array", "items": {"type": "string"},
                                                                         "minItems": 2, "maxItems": 3}},
                         "required": ["model_ids"], "additionalProperties": False},
    },
    {
        "name": "select_model",
        "description": "Start (or switch) the configuration on a model. Compatible options are carried over; "
                       "dropped ones are reported.",
        "input_schema": {"type": "object", "properties": {"model_id": {"type": "string"}}, "required": ["model_id"],
                         "additionalProperties": False},
    },
    {
        "name": "change_option",
        "description": "Add or remove an option on the selected model. The rules engine auto-adds dependencies, rejects "
                       "options not offered on the model, and returns a conflict (with resolutions) instead of silently "
                       "removing something the customer chose. Only set force=true after the customer explicitly "
                       "accepted the conflict resolution.",
        "input_schema": {"type": "object", "properties": {
            "action": {"enum": ["add", "remove"]}, "option_id": {"type": "string"}, "force": {"type": "boolean"}},
            "required": ["action", "option_id"], "additionalProperties": False},
    },
    {
        "name": "get_configuration",
        "description": "Current configuration with price breakdown, budget status, validity, unmet requirements, "
                       "recommended options and savings suggestions.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "show_ui",
        "description": "Show adaptive UI next to your reply. The backend fills in all data (prices, specs) from the "
                       "catalog. Use: 'question' for a focused clarification with 2-5 short answer choices; "
                       "'preference_slider' for comfort vs. sportiness; 'model_cards' with model_ids from search results; "
                       "'comparison' with 2-3 model_ids; 'tradeoffs' to offer the trade-offs from the last search; "
                       "'option_toggles' with option_ids (omit for recommended options); 'summary' for the final "
                       "configuration. At most 3 components per turn.",
        "input_schema": {
            "type": "object",
            "properties": {"components": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                "type": "object",
                "properties": {
                    "type": {"enum": ["question", "preference_slider", "model_cards", "comparison", "tradeoffs",
                                      "option_toggles", "summary"]},
                    "prompt": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "topic": {"type": "string", "description": "Short key for a question topic, e.g. 'towing'"},
                    "model_ids": {"type": "array", "items": {"type": "string"}},
                    "option_ids": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                },
                "required": ["type"],
                "additionalProperties": False,
            }}},
            "required": ["components"],
            "additionalProperties": False,
        },
    },
]


# --------------------------------------------------------------------------- toolbox


class Toolbox:
    def __init__(self, catalog: CatalogClient, state: SessionState, error_notices: bool = True):
        self.catalog = catalog
        self.state = state
        self.components: list[dict] = []
        self.error_notices = error_notices
        self.view: dict | None = None  # latest configuration view

    # -- helpers ---------------------------------------------------------------

    def _remember(self, evaluations: list[dict]) -> None:
        for ev in evaluations:
            self.state.evaluations[ev["model_id"]] = ev

    async def _evaluations(self, model_ids: list[str]) -> list[dict]:
        missing = [m for m in model_ids if m not in self.state.evaluations]
        if missing:
            try:
                res = await self.catalog.recommend(self.state.requirements, model_ids=missing)
            except CatalogError as exc:
                raise ToolError(f"Unknown model id in {missing}: {exc.detail}") from exc
            self._remember(res["fits"] + res["near_misses"])
        return [self.state.evaluations[m] for m in model_ids if m in self.state.evaluations]

    async def current_view(self) -> dict | None:
        if not self.state.model_id:
            return None
        self.view = await self.catalog.view(self.state.model_id, self.state.options, self.state.requirements)
        return self.view

    @staticmethod
    def summarize_view(view: dict) -> dict:
        return {
            "model_id": view["model_id"],
            "model": view["model_name"],
            "total_price": view["total_price"],
            "budget": view["budget"],
            "valid": view["valid"],
            "issues": [i["message"] for i in view["issues"]],
            "unmet_requirements": [v["message"] for v in view["unmet_requirements"]],
            "selected": [{"id": line["id"], "name": line["name"], "price": line["price"], "status": line["status"],
                          "reason": line["reason"]} for line in view["lines"]],
            "recommended_options": [{"id": o["id"], "name": o["name"], "price": o["price"], "reason": o["recommended_reason"]}
                                    for o in view["catalog_options"] if o["recommended"]],
            "available_options": [{"id": o["id"], "name": o["name"], "price": o["price"]}
                                  for o in view["catalog_options"] if o["state"] == "available"],
            "unavailable_options": [o["id"] for o in view["catalog_options"] if o["state"] == "unavailable"],
            "savings_if_over_budget": view["savings"],
            "specs": view["specs"],
        }

    # -- tools -----------------------------------------------------------------

    async def update_requirements(self, patch: dict, assumptions: list[str] | None = None) -> dict:
        try:
            new = self.state.requirements.merged(patch)
        except (ValueError, ValidationError) as exc:
            raise ToolError(f"Invalid requirements patch: {exc}") from exc
        changed = {k: v for k, v in new.model_dump().items() if self.state.requirements.model_dump()[k] != v}
        self.state.requirements = new
        for a in assumptions or []:
            if a not in self.state.assumptions:
                self.state.assumptions.append(a)
        self.state.evaluations = {}  # rankings depend on requirements
        result: dict = {"requirements": new.model_dump(exclude_defaults=True), "changed": list(changed)}
        view = await self.current_view()
        if view:
            result["current_configuration_still_fits"] = not view["unmet_requirements"]
            result["unmet_requirements"] = [v["message"] for v in view["unmet_requirements"]]
            result["total_price"] = view["total_price"]
        return result

    async def search_models(self, limit: int = 3) -> dict:
        res = await self.catalog.recommend(self.state.requirements, limit=limit)
        self._remember(res["fits"] + res["near_misses"])
        self.state.last_tradeoffs = res["tradeoffs"]
        return {
            "explanation": res["explanation"],
            "fits": [{"model_id": e["model_id"], "name": e["name"], "entry_price": e["entry_price"],
                      "score": e["score"], "reasons": e["reasons"], "required_options": e["required_options"]}
                     for e in res["fits"]],
            "near_misses": [{"model_id": e["model_id"], "name": e["name"], "entry_price": e["entry_price"],
                             "violations": [v["message"] for v in e["violations"]]} for e in res["near_misses"]],
            "tradeoffs": [{"label": t["label"], "description": t["description"], "model_id": t["model_id"]}
                          for t in res["tradeoffs"]],
        }

    async def compare_models(self, model_ids: list[str]) -> dict:
        res = await self.catalog.recommend(self.state.requirements, model_ids=model_ids)
        evs = res["fits"] + res["near_misses"]
        self._remember(evs)
        return {"models": [{"model_id": e["model_id"], "name": e["name"], "entry_price": e["entry_price"],
                            "fits": e["fits"], "violations": [v["message"] for v in e["violations"]],
                            "specs": e["specs"], "reasons": e["reasons"]} for e in evs]}

    async def select_model(self, model_id: str) -> dict:
        previous = self.state.options if self.state.model_id else []
        try:
            res = await self.catalog.switch_model(model_id, previous, self.state.requirements)
        except CatalogError as exc:
            raise ToolError(f"Unknown model '{model_id}'. Use a model_id from search_models.") from exc
        self.state.model_id = model_id
        self.state.options = res["configuration"]["options"]
        self.view = res["configuration"]
        notes = [n["message"] for n in res["notes"]]
        # Options the customer's requirements depend on (e.g. tow hitch) are added straight away,
        # so the configured price matches the price shown on the recommendation card.
        evaluation = (await self._evaluations([model_id]) or [{}])[0]
        for oid in evaluation.get("required_options", []):
            if oid in self.state.options:
                continue
            change = await self.catalog.change(model_id, self.state.options, self.state.requirements, "add", oid)
            if change["status"] == "applied":
                self.state.options = change["configuration"]["options"]
                self.view = change["configuration"]
                name = next(o["name"] for o in self.view["catalog_options"] if o["id"] == oid)
                notes.append(f"Added {name} because your requirements need it.")
        out = self.summarize_view(self.view)
        out["notes"] = notes
        return out

    async def change_option(self, action: str, option_id: str, force: bool = False) -> dict:
        if not self.state.model_id:
            raise ToolError("No model selected yet. Call select_model first.")
        res = await self.catalog.change(self.state.model_id, self.state.options, self.state.requirements,
                                        action, option_id, force)
        self.state.options = res["configuration"]["options"]
        self.view = res["configuration"]
        out: dict = {"status": res["status"], "notes": [n["message"] for n in res["notes"]],
                     "total_price": self.view["total_price"], "budget": self.view["budget"]}
        if res["conflict"]:
            out["conflict"] = res["conflict"]["message"]
            out["resolutions"] = [r["label"] for r in res["conflict"]["resolutions"]]
            self.components.append(ui.conflict(res["conflict"]))
        if res["error"]:
            out["error"] = res["error"]["message"]
            if self.error_notices:
                self.components.append(ui.notice(res["error"]["message"], "error"))
        if self.view["budget"]["over_by"]:
            out["savings_if_over_budget"] = self.view["savings"]
        return out

    async def get_configuration(self) -> dict:
        view = await self.current_view()
        if not view:
            return {"selected_model": None, "message": "No model selected yet."}
        return self.summarize_view(view)

    async def show_ui(self, components: list[UIComponentSpec]) -> dict:
        shown: list[str] = []
        for spec in components:
            comp = await self._build(spec)
            self.components.append(comp)
            shown.append(spec.type)
        return {"shown": shown}

    async def _build(self, spec: UIComponentSpec) -> dict:
        if spec.type == "question":
            if not spec.prompt or len(spec.choices) < 2:
                raise ToolError("A question needs a prompt and at least two choices.")
            if spec.topic:
                self.state.asked.append(spec.topic)
            return ui.question(spec.prompt, spec.choices, spec.topic or "")
        if spec.type == "preference_slider":
            self.state.asked.append("sportiness")
            return ui.slider(self.state.requirements, spec.prompt or "What matters more to you on the road?")
        if spec.type in ("model_cards", "comparison"):
            if not spec.model_ids:
                raise ToolError(f"{spec.type} needs model_ids.")
            evs = await self._evaluations(spec.model_ids)
            if spec.type == "comparison":
                if len(evs) < 2:
                    raise ToolError("comparison needs 2-3 valid model_ids.")
                return ui.comparison(evs)
            return ui.model_cards(evs, spec.title or "Recommended for you")
        if spec.type == "tradeoffs":
            if not self.state.last_tradeoffs:
                raise ToolError("No trade-offs available; call search_models first.")
            return ui.tradeoffs(self.state.last_tradeoffs, spec.title or "Possible trade-offs")
        view = self.view or await self.current_view()
        if not view:
            raise ToolError(f"{spec.type} needs a selected model; call select_model first.")
        if spec.type == "option_toggles":
            return ui.option_toggles(view, spec.option_ids or None, spec.title or "Suggested options")
        return ui.summary(view, self.state.requirements, self.state.assumptions)

    # -- dispatcher used by the Claude agent -----------------------------------

    async def execute(self, name: str, raw_input: dict) -> dict:
        try:
            if name == "update_requirements":
                args = UpdateRequirementsInput.model_validate(raw_input)
                return await self.update_requirements(args.patch, args.assumptions)
            if name == "search_models":
                return await self.search_models(SearchInput.model_validate(raw_input).limit)
            if name == "compare_models":
                return await self.compare_models(CompareInput.model_validate(raw_input).model_ids)
            if name == "select_model":
                return await self.select_model(SelectModelInput.model_validate(raw_input).model_id)
            if name == "change_option":
                args = ChangeOptionInput.model_validate(raw_input)
                return await self.change_option(args.action, args.option_id, args.force)
            if name == "get_configuration":
                return await self.get_configuration()
            if name == "show_ui":
                return await self.show_ui(ShowUIInput.model_validate(raw_input).components)
        except ValidationError as exc:
            raise ToolError(f"Invalid input for {name}: {exc.errors(include_url=False)}") from exc
        raise ToolError(f"Unknown tool '{name}'")
