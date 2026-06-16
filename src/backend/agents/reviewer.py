"""Reviewer agent handler in demo mode (example validation output)."""
from __future__ import annotations

from typing import Any, MutableMapping

from purpose_app import add_message

from .constants import AGENT_REVIEWER
from .types import AgentDependencies


class ReviewerAgent:
    agent_id = AGENT_REVIEWER

    def handle(
        self,
        message: str,
        state: MutableMapping[str, Any],
        deps: AgentDependencies,
    ) -> None:
        reply = (
            "⚠️ **This agent is still under development.**\n\n"
            "The Reviewer is a placeholder — it cannot perform real validation yet.\n\n"
            "**Planned behaviour:**\n"
            "• Load predefined DDO study descriptors and compliance rules\n"
            "• Compare each field in your structured purpose against those rules\n"
            "• Produce a per-rule pass/fail report with an overall compliance score\n"
            "• Emit an approval recommendation (approve / request changes)\n\n"
            "_Please use the **Purpose Tuner** to build and ontology-validate your purpose in the meantime._"
        )
        state["last_raw_response"] = ""
        state["last_response_fallback"] = False
        add_message("assistant", reply)
