from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    root_node_id: str
    expected_revision: int
    name: str
    bg_color: str = "#6366f1"
    text_color: str = "#ffffff"
    one_only: bool = False
    track_history: bool = False


class TagUpdate(BaseModel):
    root_node_id: str
    tag_id: str
    expected_revision: int
    name: str | None = None
    bg_color: str | None = None
    text_color: str | None = None
    one_only: bool | None = None
    track_history: bool | None = None


class TagDelete(BaseModel):
    root_node_id: str
    tag_id: str
    expected_revision: int


class TagAssignment(BaseModel):
    node_id: str
    expected_revision: int
    tag_ids: list[str]


class TagResponse(BaseModel):
    tag_id: str
    name: str
    bg_color: str
    text_color: str
    one_only: bool = False
    track_history: bool = False
    history_next_index: int = 0


class TagHistoryEntry(BaseModel):
    tag_id: str
    history_index: int
    superseded_at: str
    superseded_by_node_id: str
