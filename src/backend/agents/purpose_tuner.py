"""Purpose tuner agent handler: extraction, normalization, and guided prompting."""
from __future__ import annotations

from typing import Any, Dict, MutableMapping

from purpose_app import (
    add_message,
    build_assistant_reply,
    build_optimizer_reply,
    build_reviewer_reply,
    detect_intent,
    update_structured_data,
)

from .constants import (
    AGENT_OPTIMIZER,
    AGENT_PURPOSE_TUNER,
    AGENT_REVIEWER,
    FALLBACK_RESPONSE,
)
from .routing import parse_purpose_selection
from .types import AgentDependencies


class PurposeTunerAgent:
    agent_id = AGENT_PURPOSE_TUNER

    def handle(
        self,
        message: str,
        state: MutableMapping[str, Any],
        deps: AgentDependencies,
    ) -> None:
        if state.get("pending_purpose_selection") or not state.get("selected_purpose"):
            selected = parse_purpose_selection(message)
            if not selected:
                from .prompts import purpose_tuner_prompt

                state["pending_purpose_selection"] = True
                add_message("assistant", purpose_tuner_prompt())
                return

            state["selected_purpose"] = selected
            state["pending_purpose_selection"] = False
            add_message(
                "assistant",
                f"Great — we'll focus on {selected}. Tell me about the diseases, medication, product development, and therapeutic area.",
            )
            return

        intent = detect_intent(message)
        state["last_intent"] = intent

        if intent == "support":
            support_reply = deps.call_support_model(message, state)
            state["last_raw_response"] = ""
            state["last_response_fallback"] = False
            add_message("assistant", support_reply)
            return

        user_messages = [item["content"] for item in state.get("messages", []) if item.get("role") == "user"]
        result = deps.graph.invoke({"user_messages": user_messages})
        raw_response = result.get("raw_response", "")
        structured = result.get("structured")

        if isinstance(structured, dict):
            update_structured_data(structured)

        structured_data = state.get("structured_data") or {}
        if structured is None and raw_response:
            assistant_reply = FALLBACK_RESPONSE
        elif intent == AGENT_OPTIMIZER:
            assistant_reply = build_optimizer_reply(structured_data)
        elif intent == AGENT_REVIEWER:
            assistant_reply = build_reviewer_reply(structured_data)
        else:
            assistant_reply = build_assistant_reply(structured_data)

        state["last_raw_response"] = raw_response
        state["last_response_fallback"] = bool(structured is None and raw_response)
        add_message("assistant", assistant_reply)
