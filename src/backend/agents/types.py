"""Shared typing contracts for backend agent handlers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, MutableMapping, Protocol


class GraphRunner(Protocol):
    """Minimal protocol for the LangGraph runner used by handlers."""

    def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...


@dataclass(slots=True)
class AgentDependencies:
    graph: GraphRunner
    call_support_model: Callable[[str, Dict[str, Any]], str]


class AgentHandler(Protocol):
    agent_id: str

    def handle(
        self,
        message: str,
        state: MutableMapping[str, Any],
        deps: AgentDependencies,
    ) -> None:
        ...
