from __future__ import annotations

from pydantic import BaseModel, Field

from .common import CollaboratorRole, SharingMode


class Collaborator(BaseModel):
    email: str
    role: CollaboratorRole


class SetSharingRequest(BaseModel):
    node_id: str
    sharing_mode: SharingMode | None = None
    collaborators: list[Collaborator] | None = None


class SetSharingBatchRequest(BaseModel):
    node_ids: list[str]
    sharing_mode: SharingMode | None = None
    collaborators: list[Collaborator] | None = None


class EffectivePermissions(BaseModel):
    can_view: bool = False
    can_write: bool = False
    can_admin: bool = False


class SharingResponse(BaseModel):
    node_id: str
    owner_user_id: str
    owner_email: str
    is_owner: bool
    collaboration_enabled: bool = False
    sharing_mode: SharingMode = SharingMode.private
    visibility: str = "private"
    effective: EffectivePermissions = Field(default_factory=EffectivePermissions)
    collaborators: list[Collaborator] = Field(default_factory=list)
    updated_at: str = ""
