import uuid
from datetime import datetime
from pydantic import BaseModel

class CheckoutSessionRequest(BaseModel):
    plan_tier: str # pro, team

class CheckoutSessionResponse(BaseModel):
    checkout_url: str

class InvoiceOut(BaseModel):
    id: uuid.UUID
    stripe_invoice_id: str
    amount: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
