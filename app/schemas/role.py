from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedResponse


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_codes: list[str] | None = None


class RoleResponse(TimestampedResponse):
    tenant_id: UUID | None
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]


class AssignRoleRequest(BaseModel):
    user_id: UUID
    role_id: UUID
    scope_tenant_id: UUID | None = None
