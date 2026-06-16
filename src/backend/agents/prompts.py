"""Prompt builders for each conversational agent."""
from __future__ import annotations

from .constants import PURPOSE_OPTIONS


def receptionist_prompt() -> str:
    return (
        "**Hi! I'm the Receptionist.** I tell you how things work and where to get information.\n\n"
        "I can connect you with:\n\n"
        "1) **Purpose Tuner** – Help specify and form your research purpose\n"
        "2) **Optimizer** ⚠️ _(under development)_ – Match existing use cases and avoid redundancy\n"
        "3) **Reviewer** ⚠️ _(under development)_ – Validate purposes for DDO against study descriptors\n\n"
        "Which would you like?"
    )


def support_prompt() -> str:
    return (
        "**Support** ready. I search for existing knowledge and solutions.\n\n"
        "I can help with:\n"
        "• Answers to common questions\n"
        "• Links to documentation\n"
        "• Guidance on tool features\n\n"
        "What would you like to know?"
    )


def purpose_tuner_prompt() -> str:
    lines = [
        "**Purpose Tuner** ready. I help you find and properly form an optimal research purpose.\n",
        "I can:\n"
        "• Help specify your purpose\n"
        "• Match with descriptors\n"
        "• Link to vocabularies\n\n",
        "First, choose a purpose category by number or name:",
    ]
    for idx, option in enumerate(PURPOSE_OPTIONS, start=1):
        lines.append(f"{idx}. {option}")
    return "\n".join(lines)


def reviewer_prompt() -> str:
    return (
        "⚠️ **Reviewer — Under Development**\n\n"
        "This agent is still being built and is not yet functional.\n\n"
        "**What to expect once ready:**\n"
        "• Validate your purpose against predefined DDO study descriptors\n"
        "• Per-rule compliance report with pass/fail breakdown\n"
        "• Overall conformance score and approval recommendation\n"
        "• Actionable feedback on missing or invalid fields\n\n"
        "_For now, please use the **Purpose Tuner** to build and validate your purpose._"
    )


def optimizer_prompt() -> str:
    return (
        "⚠️ **Optimizer — Under Development**\n\n"
        "This agent is still being built and is not yet functional.\n\n"
        "**What to expect once ready:**\n"
        "• Match your purpose against an existing approved use-case database\n"
        "• Similarity scoring to surface near-duplicate requests\n"
        "• Scope-adjustment suggestions to reuse already-approved work\n"
        "• Cross-user and cross-session deduplication\n\n"
        "_For now, please use the **Purpose Tuner** to build and validate your purpose._"
    )
