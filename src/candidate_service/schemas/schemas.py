import re
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, field_validator, Field, ConfigDict


class CreateOperationRequest(BaseModel):
    operationId: str
    amount: str
    currency: str = "RUB"
    description: str = ""

    @field_validator('amount')
    @classmethod
    def amount_validator(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d{1,2}$", v):
            raise ValueError("Invalid amount format")

        if float(v) < 0:
            raise ValueError("Amount must be positive")

        return v

    @field_validator('currency')
    @classmethod
    def description_validator(cls, v: str) -> str:
        if v != "RUB":
            raise ValueError("Only RUB is supported")

        return v


class OperationResponse(BaseModel):
    operationId: str
    amount: str
    currency: str
    description: str
    status: str
    providerPaymentId: str | None


class ReceiptRequest(BaseModel):
    providerPaymentId: str
    operationId: str
    result: Literal["COMPLETED", "REJECTED"]
    message: str | None = None
    occurredAt: datetime

class EventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: int = Field(alias="eventId", serialization_alias="eventId")
    event_type: str = Field(alias="type",serialization_alias="type")
    from_status: str | None = Field(default=None, alias="fromStatus", serialization_alias="fromStatus")
    to_status: str = Field(alias="toStatus", serialization_alias="toStatus")
    message: str | None = None
    occurred_at: datetime = Field(alias="occurredAt", serialization_alias="occurredAt")