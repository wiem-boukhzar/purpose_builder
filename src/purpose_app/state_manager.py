"""Shared session-state adapter so purpose_app logic can run inside Streamlit or FastAPI."""
from __future__ import annotations

import contextvars
from typing import Any, MutableMapping, Optional

_session_state_var: contextvars.ContextVar[Optional[MutableMapping[str, Any]]] = contextvars.ContextVar(
    "purpose_app_session_state", default=None
)


def configure_session_state(state: MutableMapping[str, Any]) -> None:
    """Bind a custom session state mapping for the current context."""
    _session_state_var.set(state)


def get_session_state() -> MutableMapping[str, Any]:
    """Return the active session state, falling back to Streamlit's global state."""
    state = _session_state_var.get()
    if state is not None:
        return state

    try:
        import streamlit as st

        return st.session_state
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            "purpose_app session state is not configured and Streamlit is unavailable."
        ) from exc
