"""Pydantic request/response schemas used by backend.api endpoints and tests."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    session_id: str
    state: Dict[str, Any]


class MessageRequest(BaseModel):
    content: str = Field(..., description="User message content")


class SelectionRequest(BaseModel):
    raw: str = Field(..., description="Raw disease string keyed by the backend")
    selections: List[str] = Field(default_factory=list, description="List of leaf display strings to select")


class PurposeRequest(BaseModel):
    purpose: str = Field(..., description="User-selected research purpose label")


class CollaboratorRequest(BaseModel):
    collaborator: bool = Field(..., description="Whether a collaborator is involved")


class FaqContextRequest(BaseModel):
    context: str = Field(..., description="FAQ context text used by the FAQ agent")
