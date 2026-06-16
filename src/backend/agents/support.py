"""Support agent handler that answers user questions against support context."""
from __future__ import annotations

from typing import Any, MutableMapping

from purpose_app import add_message

from .constants import AGENT_SUPPORT
from .types import AgentDependencies


class SupportAgent:
    agent_id = AGENT_SUPPORT

    def handle(
        self,
        message: str,
        state: MutableMapping[str, Any],
        deps: AgentDependencies,
    ) -> None:
        support_reply = deps.call_support_model(message, state)
        state["last_raw_response"] = ""
        state["last_response_fallback"] = False
        add_message("assistant", support_reply)
