"""Optimizer agent handler in demo mode (example use-case matching output)."""
from __future__ import annotations

from typing import Any, MutableMapping

from purpose_app import add_message

from .constants import AGENT_OPTIMIZER
from .types import AgentDependencies


class OptimizerAgent:
    agent_id = AGENT_OPTIMIZER

    def handle(
        self,
        message: str,
        state: MutableMapping[str, Any],
        deps: AgentDependencies,
    ) -> None:
        reply = (
            "⚠️ **This agent is still under development.**\n\n"
            "The Optimizer is a placeholder — it cannot perform real use-case matching yet.\n\n"
            "**Planned behaviour:**\n"
            "• Query a persistent, cross-user use-case database\n"
            "• Run vector similarity search on purpose descriptions to surface near-duplicates\n"
            "• Return ranked matches with reuse options and similarity scores\n"
            "• Suggest scope adjustments to align with already-approved work\n\n"
            "_Please use the **Purpose Tuner** to build and ontology-validate your purpose in the meantime._"
        )
        state["last_raw_response"] = ""
        state["last_response_fallback"] = False
        add_message("assistant", reply)
