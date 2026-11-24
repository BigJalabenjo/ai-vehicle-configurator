"""Conversation state and session storage.

The in-memory store is used for the prototype. ``SessionStore`` is the seam
for a production store (DynamoDB / Redis with TTL); state is plain JSON-able
data so it can be persisted as-is.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .domain import Requirements


class SessionState(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    requirements: Requirements = Requirements()
    assumptions: list[str] = []
    model_id: str | None = None
    options: list[str] = []
    asked: list[str] = Field(default=[], description="Clarification topics already asked (avoid repeats)")
    evaluations: dict[str, dict] = Field(default={}, description="Latest model evaluations by id (UI hydration)")
    last_tradeoffs: list[dict] = []
    llm_history: list[dict[str, Any]] = Field(default=[], description="Provider-native LLM history (AI mode)")
    ui_events: list[str] = Field(default=[], description="UI actions not yet seen by the LLM")
    transcript: list[dict[str, Any]] = Field(default=[], description="Rendered conversation, for reloads")
    turns: int = 0


class SessionStore(Protocol):
    async def create(self) -> SessionState: ...
    async def get(self, session_id: str) -> SessionState | None: ...
    async def save(self, state: SessionState) -> None: ...
    def lock(self, session_id: str) -> asyncio.Lock: ...


class InMemorySessionStore:
    def __init__(self, ttl_s: int = 3600, max_sessions: int = 1000):
        self._data: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._ttl = ttl_s
        self._max = max_sessions

    def _evict(self) -> None:
        now = time.time()
        for sid in [s for s, st in self._data.items() if now - st.updated_at > self._ttl]:
            self._data.pop(sid, None)
            self._locks.pop(sid, None)
        while len(self._data) >= self._max:
            oldest = min(self._data.values(), key=lambda s: s.updated_at)
            self._data.pop(oldest.id, None)
            self._locks.pop(oldest.id, None)

    async def create(self) -> SessionState:
        self._evict()
        state = SessionState()
        self._data[state.id] = state
        return state

    async def get(self, session_id: str) -> SessionState | None:
        state = self._data.get(session_id)
        if state and time.time() - state.updated_at > self._ttl:
            self._data.pop(session_id, None)
            return None
        return state

    async def save(self, state: SessionState) -> None:
        state.updated_at = time.time()
        self._data[state.id] = state

    def lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())
