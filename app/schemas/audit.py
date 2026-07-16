from datetime import datetime
from typing import Any
from uuid import UUID

from app.schemas.common import ORMModel


class AuditLogEntry(ORMModel):
    id: UUID
    created_at: datetime
    actor_user_id: UUID | None
    actor_ip: str | None
    acting_from_tenant_id: UUID | None
    action: str
    resource_type: str | None
    resource_id: str | None
    request_id: str | None
    diff: dict[str, Any]
