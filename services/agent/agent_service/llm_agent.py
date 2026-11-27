"""Provider-neutral LLM agent: the tool loop, system prompt and state injection.

The loop is ours (not a hosted agent runtime) because every tool call must go
through our own rules engine, the loop needs a hard step limit, and the
conversation state lives in our session store. Provider specifics (request
shape, message format, error types) live in ``providers/``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .config import Settings
from .toolbox import Toolbox, ToolError

log = logging.getLogger("agent.llm")

SYSTEM_TEMPLATE = """You are the vehicle configuration assistant of a car brand's online configurator. You help a customer \
go from a description of their needs to a valid, explainable vehicle configuration.

How to work:
- Translate what the customer says into structured requirements with update_requirements. Distinguish soft \
preferences ("I prefer electric" -> powertrain_preferred) from hard constraints ("must be electric" -> \
powertrain_required). Record each interpretation you make as an assumption so the customer can correct it.
- Then call search_models and present the best matches with show_ui (model_cards). If nothing fits, explain the \
conflict plainly and offer the trade-offs (show_ui tradeoffs) - never pretend a model fits. Only show trade-offs \
right after a search that produced them and when they are relevant to what the customer just asked.
- Clarify in a focused way: while no model is selected yet, end each recommendation turn with exactly one question \
about the most important unknown that could still change the ranking or the configuration - typically the budget if \
missing, how many people travel, towing needs (bike carrier, trailer, caravan), or comfort vs. sportiness (use \
'preference_slider' for that one). Use show_ui 'question' with 2-5 short answer choices and set its topic. Skip the \
question only when none of these is unknown. Never ask about topics listed in <state> as already asked, never more \
than one question per turn, and never ask for personal data (name, address, phone, e-mail).
- When tool calls do not depend on each other's results, make them in the same response (e.g. update_requirements \
and search_models together).
- When the customer picks a model, call select_model, then suggest a few options that fit their needs \
(show_ui option_toggles).
- Option changes go through change_option. If it returns a conflict or error, explain it in one or two sentences; \
the UI already shows the resolution buttons. Use force=true only after the customer explicitly chose to accept the \
resolution.
- When requirements change, update them, re-check the current configuration (unmet_requirements, budget), and \
re-run search_models if the selected model no longer fits.
- When the customer is done, show_ui 'summary'.

Rules:
- Every price, spec, availability or compatibility statement must come from a tool result in this conversation. \
Never estimate or invent numbers. Format euros like the tool results do: "€71,900" in English, "71.900 €" in German.
- Messages starting with [UI] describe actions the customer took in the interface; they have already been applied. \
React to them; do not repeat them.
- Keep replies short and friendly: at most 3 short paragraphs or ~90 words. The UI carries the detail, so don't \
repeat a question card's wording or list every option shown in a card.
- Always reply in the interface language given as "language" in <state> ("en" = English, "de" = German), even if \
the customer writes in another language: the customer chose it in the interface, and replies may be read aloud in it. \
Write question cards, answer choices, card titles and assumptions in that language too; use the formal "Sie" in \
German. Tool results already come in that language. Catalog ids stay as they are.

Catalog overview (ids for tool calls):
{catalog}
"""


def build_catalog_overview(catalog: dict) -> str:
    models = "\n".join(f"- {m['id']}: {m['name']} ({m['powertrain']}, {m['body']}, from €{m['base_price']:,})"
                       for m in catalog["models"])
    options = "\n".join(f"- {o['id']}: {o['name']} ({o['category']})" for o in catalog["options"])
    return f"Models:\n{models}\nOptions:\n{options}\n{catalog['disclaimer']}"


def system_prompt(catalog_overview: str) -> str:
    return SYSTEM_TEMPLATE.format(catalog=catalog_overview)


def state_block(toolbox: Toolbox) -> str:
    st = toolbox.state
    data = {
        "language": st.language,
        "requirements": st.requirements.model_dump(exclude_defaults=True),
        "assumptions": st.assumptions,
        "selected_model": st.model_id,
        "selected_options": st.options,
        "already_asked": sorted(set(st.asked)),
        "ui_events_since_last_turn": st.ui_events,
    }
    return f"<state>{json.dumps(data)}</state>"


class LLMUnavailable(RuntimeError):
    """The LLM could not be reached or declined; the orchestrator falls back to guided mode."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    parse_error: str | None = None  # provider returned arguments that are not valid JSON


@dataclass
class LLMStep:
    """One model response, normalised across providers."""

    text: str
    tool_calls: list[ToolCall]
    stop: Literal["tool_use", "end", "continue"]
    assistant_messages: list[dict]  # provider-native messages to append to the history
    usage: dict = field(default_factory=dict)


@dataclass
class ToolOutcome:
    call: ToolCall
    content: str
    is_error: bool


class LLMProvider(Protocol):
    name: str
    model: str

    def user_message(self, text: str, state: str) -> dict: ...
    async def complete(self, messages: list[dict]) -> LLMStep: ...
    def tool_result_messages(self, outcomes: list[ToolOutcome]) -> list[dict]: ...
    def closing_message(self, text: str) -> dict: ...


class LLMAgent:
    def __init__(self, settings: Settings, provider: LLMProvider):
        self.settings = settings
        self.provider = provider

    @property
    def name(self) -> str:
        return self.provider.name

    async def run(self, toolbox: Toolbox, user_text: str) -> str:
        state = toolbox.state
        messages: list[dict] = list(state.llm_history)
        messages.append(self.provider.user_message(user_text, state_block(toolbox)))
        final_text = ""
        dangling_tools = False
        for step_no in range(self.settings.llm_max_steps):
            started = time.perf_counter()
            step = await self.provider.complete(messages)
            log.info("llm provider=%s model=%s step=%d stop=%s usage=%s latency_ms=%.0f", self.provider.name,
                     self.provider.model, step_no, step.stop, step.usage, (time.perf_counter() - started) * 1000)
            messages.extend(step.assistant_messages)
            if step.text:
                final_text = step.text
            if step.stop == "continue":
                continue
            if step.stop != "tool_use" or not step.tool_calls:
                dangling_tools = False
                break
            outcomes = [await self._execute(toolbox, call) for call in step.tool_calls]
            messages.extend(self.provider.tool_result_messages(outcomes))
            dangling_tools = True
        final_text = final_text or "I've prepared what I could - let me know how you'd like to continue."
        if dangling_tools:
            # Step limit hit right after tool results: close the turn so the history stays valid.
            messages.append(self.provider.closing_message(final_text))

        state.llm_history = messages
        state.ui_events = []
        return final_text

    @staticmethod
    async def _execute(toolbox: Toolbox, call: ToolCall) -> ToolOutcome:
        if call.parse_error:
            return ToolOutcome(call, f"Invalid JSON arguments: {call.parse_error}", True)
        try:
            result = await toolbox.execute(call.name, call.input)
            return ToolOutcome(call, json.dumps(result), False)
        except ToolError as exc:
            return ToolOutcome(call, str(exc), True)
