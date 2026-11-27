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

from . import i18n, ui
from .catalog_client import CatalogClient
from .i18n import t
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


class UpdateRequirementsAction(BaseModel):
    """Needs edited on the configurator stage: a partial patch, None clears a field."""
    type: Literal["update_requirements"]
    patch: dict


class SummaryAction(BaseModel):
    type: Literal["request_summary"]


class SetLanguageAction(BaseModel):
    """The customer switched the interface language; replies, rules and voice follow it."""
    type: Literal["set_language"]
    language: i18n.Language


Action = Annotated[
    Union[AnswerAction, SelectModelAction, SetPreferenceAction, ApplyTradeoffAction, ChangeOptionAction,
          RemoveRequirementAction, UpdateRequirementsAction, SummaryAction, SetLanguageAction],
    Field(discriminator="type"),
]


class TurnRequest(BaseModel):
    message: str | None = Field(default=None, max_length=2000)
    action: Action | None = None


# --------------------------------------------------------------------------- orchestrator


class Orchestrator:
    def __init__(self, catalog: CatalogClient, agent: LLMAgent | None):
        self.catalog = catalog
        self.agent = agent
        self.offline = OfflineAgent()

    @property
    def mode(self) -> str:
        return self.agent.name if self.agent else "guided"

    def greeting(self, state: SessionState) -> dict:
        examples = [t("example_1"), t("example_2"), t("example_3")]
        message = {"role": "assistant", "text": t("greeting"),
                   "components": [ui.question(t("examples_prompt"), examples, "example")]}
        state.transcript.append(message)
        return message

    async def handle(self, state: SessionState, req: TurnRequest) -> dict:
        tb = Toolbox(self.catalog, state, error_notices=self.agent is not None)
        mode = self.mode
        if isinstance(req.action, ChangeOptionAction):
            # Option changes from the configurator UI are shown there (dialog, toast, highlights),
            # not as chat messages: no echo, no reply, no transcript entry, no LLM call.
            feedback = await self._option_change(tb, req.action)
            return {"message": None, "feedback": feedback, "mode": mode, "state": await self.snapshot(state, tb)}
        if isinstance(req.action, SetLanguageAction):
            feedback = self._language_change(state, req.action.language)
            return {"message": None, "feedback": feedback, "mode": mode, "state": await self.snapshot(state)}
        if isinstance(req.action, UpdateRequirementsAction):
            # Same for needs edited on the stage: the stage shows the result (status line, budget bar).
            feedback = await self._requirements_change(tb, req.action)
            return {"message": None, "feedback": feedback, "mode": mode, "state": await self.snapshot(state, tb)}
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
            "language": state.language,
            "requirements": [{"field": f, "label": label} for f, label in state.requirements.describe()],
            "requirement_values": state.requirements.model_dump(),
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
                tb.components = [ui.notice(t("llm_unavailable"), "warning")]
        return await self.offline.run(tb, text), "guided"

    # ------------------------------------------------------------------ actions

    @staticmethod
    def _echo(action: BaseModel, view: dict | None) -> str:
        """What the user 'said' by clicking, for the transcript."""
        match action:
            case AnswerAction(value=v):
                return v
            case SelectModelAction(model_id=m):
                return t("echo_configure", model=view["model_name"] if view and view["model_id"] == m else m)
            case SetPreferenceAction(value=v):
                return t("echo_preference", pct=round(v * 100))
            case ApplyTradeoffAction(label=label):
                return t("echo_tradeoff", label=label) if label else t("echo_tradeoff_plain")
            case RemoveRequirementAction(field=f):
                return t("echo_remove_need", field=i18n.words("field").get(f, f.replace("_", " ")))
            case SummaryAction():
                return t("echo_summary")
        return ""

    async def _handle_action(self, tb: Toolbox, action: BaseModel) -> tuple[str, str]:
        if isinstance(action, AnswerAction):
            return await self._handle_text(tb, action.value)

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
                tb.components = [ui.notice(t("llm_unavailable"), "warning")]
        return await self._narrate_offline(tb, action, result), "guided"

    async def _option_change(self, tb: Toolbox, action: ChangeOptionAction) -> dict:
        """Apply an option change from the UI and return structured feedback for the configurator."""
        try:
            await tb.change_option(action.op, action.option_id, action.force)
        except ToolError as exc:
            return {"status": "rejected", "option_id": action.option_id, "notes": [], "changed": [],
                    "conflict": None, "error": str(exc)}
        res = tb.last_change
        notes = [n["message"] for n in res["notes"]]
        conflict = ui.conflict(res["conflict"]) if res["conflict"] else None
        error = res["error"]["message"] if res["error"] else None
        # The LLM learns about it on its next turn via the state block.
        verb = "added" if action.op == "add" else "removed"
        outcome = conflict["message"] if conflict else error or " ".join(notes)
        tb.state.ui_events.append(f"Customer {verb} option {action.option_id} in the UI ({res['status']}): {outcome}")
        return {"status": res["status"], "option_id": action.option_id, "notes": notes,
                "changed": [n["option_id"] for n in res["notes"]], "conflict": conflict, "error": error}

    def _language_change(self, state: SessionState, language: str) -> dict:
        """Switch the session language. Earlier messages stay as they were; an untouched greeting is redone."""
        changed = language != state.language
        state.language = language  # type: ignore[assignment]
        i18n.use(language)
        if changed:
            if state.turns == 0:
                state.transcript = []
                self.greeting(state)
            state.ui_events.append(f"Customer switched the interface language to {i18n.NAMES[language]}.")
        return {"kind": "language", "status": "ok" if changed else "noop", "language": language}

    async def _requirements_change(self, tb: Toolbox, action: UpdateRequirementsAction) -> dict:
        """Apply needs edited on the stage and return structured feedback for the configurator."""
        try:
            result = await tb.update_requirements(action.patch)
        except ToolError as exc:
            return {"kind": "requirements", "status": "rejected", "changed": [], "unmet": [], "error": str(exc)}
        unmet = result.get("unmet_requirements", [])
        if result["changed"]:
            tb.state.ui_events.append(
                f"Customer edited their needs in the UI ({', '.join(result['changed'])}); now: "
                f"{json.dumps(result['requirements'])}. Unmet by the current configuration: {unmet or 'none'}")
        return {"kind": "requirements", "status": "ok" if result["changed"] else "noop",
                "changed": result["changed"], "unmet": unmet, "error": None}

    async def _apply(self, tb: Toolbox, action: BaseModel) -> tuple[str, dict]:
        if isinstance(action, SelectModelAction):
            result = await tb.select_model(action.model_id)
            return f"The customer chose to configure the {result['model']}", result
        if isinstance(action, SetPreferenceAction):
            result = await tb.update_requirements({"sportiness": action.value})
            return f"The customer set the comfort/sport slider to {round(action.value * 100)}% sporty", result
        if isinstance(action, ApplyTradeoffAction):
            result = await tb.update_requirements(action.patch, [t("tradeoff_assumption", label=action.label)] if action.label else [])
            return f"The customer accepted the trade-off '{action.label}'", result
        if isinstance(action, RemoveRequirementAction):
            result = await tb.update_requirements({action.field: None})
            return f"The customer removed the requirement '{action.field}'", result
        if isinstance(action, SummaryAction):
            view = await tb.current_view()
            if not view:
                raise ToolError(t("pick_model_first"))
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
