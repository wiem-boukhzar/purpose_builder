"""Routing and switching helpers for multi-agent conversation flows."""
from __future__ import annotations

import re

from .constants import (
    AGENT_OPTIMIZER,
    AGENT_PURPOSE_TUNER,
    AGENT_RECEPTIONIST,
    AGENT_REVIEWER,
    AGENT_SUPPORT,
    PURPOSE_OPTIONS,
)

_OPTION_PATTERN = re.compile(r"^\s*(?:option\s*)?(\d+)\b", re.IGNORECASE)
_SWITCH_TRIGGERS = ("switch", "go to", "use", "start", "route", "i want", "take me", "open")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def route_agent(message: str) -> str | None:
    lowered = normalize_text(message)
    if any(token in lowered for token in (
        "purpose", "purpose tuner", "build a purpose",
        "create a purpose", "specify purpose",
        "study", "research", "investigate", "disease",
        "diabetes", "indication", "therapy", "therapeutic",
        "medication", "drug", "treatment", "clinical",
        "i want to", "i need to", "i would like",
    )):
        return AGENT_PURPOSE_TUNER
    if any(token in lowered for token in (
        "review", "reviewer", "ddo",
        "validate purpose", "validation",
    )):
        return AGENT_REVIEWER
    if any(token in lowered for token in (
        "optimiz", "use case", "use-case",
        "match", "redundan", "existing", "duplicate",
    )):
        return AGENT_OPTIMIZER
    return None


def is_reset_request(message: str) -> bool:
    lowered = normalize_text(message)
    return any(token in lowered for token in ("start over", "reset", "back to receptionist", "receptionist"))


def parse_purpose_selection(message: str) -> str | None:
    match = _OPTION_PATTERN.match(message)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(PURPOSE_OPTIONS):
            return PURPOSE_OPTIONS[index]

    normalized = normalize_text(message)
    for option in PURPOSE_OPTIONS:
        if normalize_text(option) == normalized:
            return option
    return None


def should_switch_agent(message: str, target: str) -> bool:
    lowered = normalize_text(message)
    if not any(token in lowered for token in _SWITCH_TRIGGERS):
        return False

    if target == AGENT_PURPOSE_TUNER:
        return any(token in lowered for token in ("purpose", "purpose tuner", "build", "tuner"))
    if target == AGENT_REVIEWER:
        return any(token in lowered for token in ("review", "reviewer", "ddo", "validate"))
    if target == AGENT_OPTIMIZER:
        return any(token in lowered for token in ("optimiz", "use case", "match", "redundan", "duplicate"))
    return False


def resolve_switch_target(active_agent: str, message: str) -> str | None:
    if active_agent == AGENT_RECEPTIONIST:
        return None

    for target in (AGENT_PURPOSE_TUNER, AGENT_REVIEWER, AGENT_OPTIMIZER):
        if target == active_agent:
            continue
        if should_switch_agent(message, target):
            return target
    return None
