import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

class LedgerEntryOut(BaseModel):
    id: uuid.UUID
    amount: int
    transaction_type: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class BalanceResponse(BaseModel):
    balance: int
    ledger: List[LedgerEntryOut]

class ListingCreate(BaseModel):
    amount: int # amount of credits
    price: int # price in cents

class ListingOut(BaseModel):
    id: uuid.UUID
    seller_account_id: uuid.UUID
    amount: int
    price: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
