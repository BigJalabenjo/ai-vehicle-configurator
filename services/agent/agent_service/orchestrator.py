"""Turn orchestration: routes free text and UI actions to the right agent.

* Deterministic UI actions (option toggles) are applied by the rules engine
  directly - instant, no LLM call.
* Other UI actions (select model, slider, trade-off, removing a requirement)
  are applied deterministically first, then narrated by the agent.
* If the LLM is unavailable, the turn is answered by the guided agent instead,
  so the customer journey never dead-ends.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from . import ui
from .catalog_client import CatalogClient
from .llm_agent import LLMAgent, LLMUnavailable
from .offline_agent import OfflineAgent
from .state import SessionState
from .toolbox import Toolbox, ToolError

log = logging.getLogger("agent.orchestrator")


# --------------------------------------------------------------------------- request models


class AnswerAction(BaseModel):
    type: Literal["answer"]
    value: str = Field(min_length=1, max_length=200)


class SelectModelAction(BaseModel):
    type: Literal["select_model"]
    model_id: str = Field(max_length=64)


class SetPreferenceAction(BaseModel):
    type: Literal["set_preference"]
    key: Literal["sportiness"]
    value: float = Field(ge=0, le=1)


class ApplyTradeoffAction(BaseModel):
    type: Literal["apply_tradeoff"]
    patch: dict
    label: str = Field(default="", max_length=200)


class ChangeOptionAction(BaseModel):
    type: Literal["change_option"]
    op: Literal["add", "remove"]
    option_id: str = Field(max_length=64)
    force: bool = False


class RemoveRequirementAction(BaseModel):
    type: Literal["remove_requirement"]
    field: str = Field(max_length=64)


class SummaryAction(BaseModel):
    type: Literal["request_summary"]


Action = Annotated[
    Union[AnswerAction, SelectModelAction, SetPreferenceAction, ApplyTradeoffAction, ChangeOptionAction,
          RemoveRequirementAction, SummaryAction],
    Field(discriminator="type"),
]


class TurnRequest(BaseModel):
    message: str | None = Field(default=None, max_length=2000)
    action: Action | None = None


# --------------------------------------------------------------------------- orchestrator


GREETING = ("Hi! I'll help you find and configure the right car. Tell me how you'll use it - who travels with you, "
            "typical trips, powertrain preferences and budget. I'll only ask what I need.")

EXAMPLE_PROMPTS = [
    "I need a family car for regular long-distance travel. I prefer electric, need room for three children, "
    "and do not want to spend more than EUR 85,000.",
    "A sporty electric car for commuting, around €60k",
    "We need 7 seats and tow a caravan",
]


class Orchestrator:
    def __init__(self, catalog: CatalogClient, agent: LLMAgent | None):
        self.catalog = catalog
        self.agent = agent
        self.offline = OfflineAgent()

    @property
    def mode(self) -> str:
        return self.agent.name if self.agent else "guided"

    def greeting(self, state: SessionState) -> dict:
        message = {"role": "assistant", "text": GREETING,
                   "components": [ui.question("Or start from an example:", EXAMPLE_PROMPTS, "example")]}
        state.transcript.append(message)
        return message

    async def handle(self, state: SessionState, req: TurnRequest) -> dict:
        tb = Toolbox(self.catalog, state, error_notices=self.agent is not None)
        mode = self.mode
        if req.action is not None:
            text, mode = await self._handle_action(tb, req.action)
            user_echo = self._echo(req.action, tb.view)
        else:
            user_echo = req.message or ""
            text, mode = await self._handle_text(tb, user_echo)
        state.turns += 1
        if user_echo:
            state.transcript.append({"role": "user", "text": user_echo, "components": []})
        message = {"role": "assistant", "text": text, "components": tb.components}
        state.transcript.append(message)
        return {"message": message, "mode": mode, "state": await self.snapshot(state, tb)}

    async def snapshot(self, state: SessionState, tb: Toolbox | None = None) -> dict:
        tb = tb or Toolbox(self.catalog, state)
        view = tb.view if (tb.view and tb.view["model_id"] == state.model_id) else await tb.current_view()
        return {
            "requirements": [{"field": f, "label": label} for f, label in state.requirements.describe()],
            "assumptions": state.assumptions,
            "configuration": view,
        }

    # ------------------------------------------------------------------ text

    async def _handle_text(self, tb: Toolbox, text: str) -> tuple[str, str]:
        if self.agent:
            try:
                return await self.agent.run(tb, text), self.agent.name
            except LLMUnavailable as exc:
                log.warning("LLM unavailable (%s); answering in guided mode", exc)
                tb.components = [ui.notice("The AI assistant is temporarily unavailable - continuing in guided mode.", "warning")]
        return await self.offline.run(tb, text), "guided"

    # ------------------------------------------------------------------ actions

    @staticmethod
    def _echo(action: BaseModel, view: dict | None) -> str:
        """What the user 'said' by clicking, for the transcript."""
        names = {o["id"]: o["name"] for o in view["catalog_options"]} if view else {}
        match action:
            case AnswerAction(value=v):
                return v
            case SelectModelAction(model_id=m):
                return f"Configure the {view['model_name']}" if view and view["model_id"] == m else f"Configure {m}"
            case SetPreferenceAction(value=v):
                return f"Preference: {round(v * 100)}% sporty"
            case ApplyTradeoffAction(label=label):
                return f"Accept: {label}" if label else "Accept trade-off"
            case ChangeOptionAction(op=op, option_id=oid):
                return f"{op.capitalize()} {names.get(oid, oid)}"
            case RemoveRequirementAction(field=f):
                return f"Remove requirement: {f.replace('_', ' ')}"
            case SummaryAction():
                return "Show summary"
        return ""

    async def _handle_action(self, tb: Toolbox, action: BaseModel) -> tuple[str, str]:
        if isinstance(action, AnswerAction):
            return await self._handle_text(tb, action.value)

        if isinstance(action, ChangeOptionAction):
            # Deterministic, no LLM round-trip. The LLM learns about it on its next turn.
            text = await self.offline.change(tb, action.op, action.option_id, action.force)
            verb = "added" if action.op == "add" else "removed"
            tb.state.ui_events.append(f"Customer {verb} option {action.option_id} in the UI: {text}")
            return text, self.mode

        try:
            ui_text, result = await self._apply(tb, action)
        except ToolError as exc:
            return str(exc), self.mode

        if self.agent:
            try:
                prompt = f"[UI] {ui_text} (already applied). Result: {json.dumps(result)[:4000]}"
                return await self.agent.run(tb, prompt), self.agent.name
            except LLMUnavailable as exc:
                log.warning("LLM unavailable (%s); narrating action in guided mode", exc)
                tb.components = [ui.notice("The AI assistant is temporarily unavailable - continuing in guided mode.", "warning")]
        return await self._narrate_offline(tb, action, result), "guided"

    async def _apply(self, tb: Toolbox, action: BaseModel) -> tuple[str, dict]:
        if isinstance(action, SelectModelAction):
            result = await tb.select_model(action.model_id)
            return f"The customer chose to configure the {result['model']}", result
        if isinstance(action, SetPreferenceAction):
            result = await tb.update_requirements({"sportiness": action.value})
            return f"The customer set the comfort/sport slider to {round(action.value * 100)}% sporty", result
        if isinstance(action, ApplyTradeoffAction):
            result = await tb.update_requirements(action.patch, [f"Accepted trade-off: {action.label}"] if action.label else [])
            return f"The customer accepted the trade-off '{action.label}'", result
        if isinstance(action, RemoveRequirementAction):
            result = await tb.update_requirements({action.field: None})
            return f"The customer removed the requirement '{action.field}'", result
        if isinstance(action, SummaryAction):
            view = await tb.current_view()
            if not view:
                raise ToolError("Pick a model first - then I can summarise your configuration.")
            if self.agent:
                tb.components.append(ui.summary(view, tb.state.requirements, tb.state.assumptions))
            return "The customer asked for the summary; it is already displayed - add a short closing note", tb.summarize_view(view)
        raise ToolError("Unsupported action")

    async def _narrate_offline(self, tb: Toolbox, action: BaseModel, result: dict) -> str:
        if isinstance(action, SelectModelAction):
            return await self.offline.describe_selection(tb, result)
        if isinstance(action, SummaryAction):
            return await self.offline.summary(tb)
        return await self.offline.recommend(tb)
