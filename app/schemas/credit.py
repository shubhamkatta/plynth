from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.credit import CreditEntryType
from app.schemas.common import TimestampedResponse


class CreditWalletResponse(TimestampedResponse):
    tenant_id: UUID
    feature_key: str
    balance: Decimal


class CreditConsumeRequest(BaseModel):
    feature_key: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0)
    reason: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=128)


class CreditGrantRequest(BaseModel):
    feature_key: str
    amount: Decimal = Field(gt=0)
    reason: str | None = None
    reference: str | None = None


class CreditLedgerEntry(TimestampedResponse):
    wallet_id: UUID
    entry_type: CreditEntryType
    amount: Decimal
    balance_after: Decimal
    reason: str | None
    reference: str | None
