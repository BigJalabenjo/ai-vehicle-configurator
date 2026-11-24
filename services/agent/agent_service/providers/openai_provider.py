"""OpenAI Chat Completions adapter (function calling)."""

from __future__ import annotations

import json
import logging

import openai

from ..llm_agent import LLMStep, LLMUnavailable, ToolCall, ToolOutcome
from ..toolbox import TOOLS

log = logging.getLogger("agent.openai")

OPENAI_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
    for t in TOOLS
]


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, system_prompt: str, effort: str | None = None, timeout_s: float = 60,
                 client: openai.AsyncOpenAI | None = None):
        self.model = model
        self.effort = effort
        # The SDK reads OPENAI_API_KEY from the environment; it is never passed or logged here.
        self.client = client or openai.AsyncOpenAI(timeout=timeout_s, max_retries=2)
        self.system = {"role": "system", "content": system_prompt}

    def user_message(self, text: str, state: str) -> dict:
        return {"role": "user", "content": f"{text}\n\n{state}"}

    def closing_message(self, text: str) -> dict:
        return {"role": "assistant", "content": text}

    def tool_result_messages(self, outcomes: list[ToolOutcome]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": o.call.id,
                 "content": f"ERROR: {o.content}" if o.is_error else o.content} for o in outcomes]

    async def complete(self, messages: list[dict]) -> LLMStep:
        kwargs: dict = dict(
            model=self.model,
            messages=[self.system, *messages],  # system prompt is not stored in the session history
            tools=OPENAI_TOOLS,
            max_completion_tokens=16000,
        )
        if self.effort:  # only reasoning models accept this; leave unset for others
            kwargs["reasoning_effort"] = self.effort
        try:
            response = await self.client.chat.completions.create(**kwargs)
        except openai.RateLimitError as exc:
            raise LLMUnavailable("rate limited or out of quota") from exc
        except openai.AuthenticationError as exc:
            raise LLMUnavailable("authentication failed - check OPENAI_API_KEY") from exc
        except openai.BadRequestError as exc:
            log.error("bad request to OpenAI: %s", exc.message)
            raise LLMUnavailable("bad request") from exc
        except openai.APIStatusError as exc:
            raise LLMUnavailable(f"API error {exc.status_code}") from exc
        except openai.APIConnectionError as exc:  # includes timeouts
            raise LLMUnavailable("connection error") from exc

        choice = response.choices[0]
        message = choice.message
        if choice.finish_reason == "content_filter" or getattr(message, "refusal", None):
            raise LLMUnavailable("request declined")

        calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            if tc.type != "function":
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
                calls.append(ToolCall(tc.id, tc.function.name, args if isinstance(args, dict) else {}))
            except json.JSONDecodeError as exc:
                calls.append(ToolCall(tc.id, tc.function.name, {}, parse_error=str(exc)))

        assistant: dict = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            assistant["tool_calls"] = [tc.model_dump(mode="json", exclude_none=True) for tc in message.tool_calls]
        usage = response.usage
        return LLMStep(
            text=(message.content or "").strip(),
            tool_calls=calls,
            stop="tool_use" if calls else "end",
            assistant_messages=[assistant],
            usage={"in": usage.prompt_tokens, "out": usage.completion_tokens} if usage else {},
        )
