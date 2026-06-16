"""Agent registry and activation/switch orchestration for backend chat turns."""
from __future__ import annotations

from typing import Any, Dict, MutableMapping

from purpose_app import add_message

from .constants import (
    AGENT_OPTIMIZER,
    AGENT_PURPOSE_TUNER,
    AGENT_RECEPTIONIST,
    AGENT_REVIEWER,
    AGENT_SUPPORT,
    PURPOSE_TUNER_CAPTURE_PROMPT,
)
from .optimizer import OptimizerAgent
from .prompts import optimizer_prompt, purpose_tuner_prompt, receptionist_prompt, reviewer_prompt
from .purpose_tuner import PurposeTunerAgent
from .receptionist import ReceptionistAgent
from .reviewer import ReviewerAgent
from .routing import resolve_switch_target
from .support import SupportAgent
from .types import AgentDependencies, AgentHandler


class AgentRegistry:
    """Owns agent handlers and shared switching/activation behavior."""

    def __init__(self, deps: AgentDependencies) -> None:
        self._deps = deps
        self._handlers: Dict[str, AgentHandler] = {}
        self._handlers[AGENT_PURPOSE_TUNER] = PurposeTunerAgent()
        self._handlers[AGENT_SUPPORT] = SupportAgent()
        self._handlers[AGENT_REVIEWER] = ReviewerAgent()
        self._handlers[AGENT_OPTIMIZER] = OptimizerAgent()
        self._handlers[AGENT_RECEPTIONIST] = ReceptionistAgent(self.activate_agent)

    def activate_agent(self, state: MutableMapping[str, Any], target: str) -> None:
        state["active_agent"] = target

        if target == AGENT_RECEPTIONIST:
            state["pending_purpose_selection"] = False
            add_message("assistant", receptionist_prompt())
            return

        if target == AGENT_PURPOSE_TUNER:
            if not state.get("selected_purpose"):
                state["pending_purpose_selection"] = True
                add_message("assistant", purpose_tuner_prompt())
                return

            state["pending_purpose_selection"] = False
            add_message("assistant", PURPOSE_TUNER_CAPTURE_PROMPT)
            return

        state["pending_purpose_selection"] = False
        if target == AGENT_REVIEWER:
            add_message("assistant", reviewer_prompt())
            return
        if target == AGENT_OPTIMIZER:
            add_message("assistant", optimizer_prompt())
            return

        state["active_agent"] = AGENT_RECEPTIONIST
        add_message("assistant", receptionist_prompt())

    def maybe_switch_agent(self, state: MutableMapping[str, Any], message: str) -> bool:
        active_agent = str(state.get("active_agent", AGENT_RECEPTIONIST))
        target = resolve_switch_target(active_agent, message)
        if target is None:
            return False

        self.activate_agent(state, target)
        return True

    def handle(self, state: MutableMapping[str, Any], message: str) -> None:
        agent_id = str(state.get("active_agent", AGENT_RECEPTIONIST))
        handler = self._handlers.get(agent_id)
        if handler is None:
            state["active_agent"] = AGENT_RECEPTIONIST
            handler = self._handlers[AGENT_RECEPTIONIST]

        handler.handle(message, state, self._deps)
