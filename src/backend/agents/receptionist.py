"""Receptionist agent handler that routes users to specialist agents."""
from __future__ import annotations

from typing import Any, Callable, MutableMapping

from purpose_app import add_message

from .routing import route_agent
from .prompts import receptionist_prompt
from .types import AgentDependencies
from .constants import AGENT_RECEPTIONIST


class ReceptionistAgent:
    agent_id = AGENT_RECEPTIONIST

    def __init__(self, activate_agent: Callable[[MutableMapping[str, Any], str], None]) -> None:
        self._activate_agent = activate_agent

    def handle(
        self,
        message: str,
        state: MutableMapping[str, Any],
        deps: AgentDependencies,
    ) -> None:
        route = route_agent(message)
        if route is not None:
            self._activate_agent(state, route)
            return

        add_message(
            "assistant",
            "I'm not sure which agent to connect you with. "
            "Could you clarify what you'd like to do?\n\n"
            "1) **Purpose Tuner** – Build or specify a research purpose\n"
            "2) **Optimizer** ⚠️ _(under development)_ – Find existing use cases or check for duplicates\n"
            "3) **Reviewer** ⚠️ _(under development)_ – Validate a purpose against study descriptors\n\n"
            "Just pick a number, name an agent, or describe your goal!",
        )
