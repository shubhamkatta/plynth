from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)


class IdResponse(BaseModel):
    id: UUID


class TimestampedResponse(ORMModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
