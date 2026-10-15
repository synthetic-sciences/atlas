from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import ArtifactType


class ArtifactResponse(BaseModel):
    artifact_id: str
    artifact_type: ArtifactType
    title: str
    note: str | None = None
    payload: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    execution_id: str | None = None
    storage_path: str = ""
    storage_url: str | None = None
    created_at: str = ""


class PrepareUploadItem(BaseModel):
    artifact_type: ArtifactType
    filename: str
    media_type: str
    title: str | None = None
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    execution_id: str | None = None


class PrepareUploadRequest(BaseModel):
    node_id: str
    expected_revision: int
    items: list[PrepareUploadItem]


class PrepareUploadResponseItem(BaseModel):
    upload_id: str
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)


class PrepareUploadResponse(BaseModel):
    batch_token: str
    expires_at: str
    max_upload_bytes: int = 10_485_760
    items: list[PrepareUploadResponseItem]


class FinalizeUploadRequest(BaseModel):
    node_id: str
    batch_token: str


class SetArtifactNoteRequest(BaseModel):
    node_id: str
    artifact_id: str
    expected_revision: int | None = None
    note: str | None = None


class DeleteArtifactRequest(BaseModel):
    node_id: str
    artifact_id: str
    expected_revision: int | None = None
