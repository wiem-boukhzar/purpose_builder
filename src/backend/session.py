"""In-memory session store used by the FastAPI backend."""
from __future__ import annotations

import threading
from typing import Dict, MutableMapping, Tuple
from uuid import uuid4


class SessionState(dict):
    """Dictionary that also supports attribute-style access like Streamlit's session_state."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


class SessionStore:
    """Thread-safe registry of active conversation sessions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def create(self) -> Tuple[str, SessionState]:
        """Create a new empty session map and return its identifier and state."""
        with self._lock:
            session_id = uuid4().hex
            state = SessionState()
            self._sessions[session_id] = state
            return session_id, state

    def get(self, session_id: str) -> SessionState | None:
        """Fetch an existing session by id if it is still in memory."""
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        """Delete the stored session state, typically when a client ends a chat."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def all_sessions(self) -> MutableMapping[str, SessionState]:
        """Return the underlying mapping for debugging or inspection tooling."""
        return self._sessions
