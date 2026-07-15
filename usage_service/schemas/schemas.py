import uuid
from typing import List
from pydantic import BaseModel

class ModelBreakdown(BaseModel):
    model: str
    tokens_used: int
    cost: int

class UsageSummary(BaseModel):
    account_id: uuid.UUID
    total_tokens: int
    total_cost: int
    breakdown: List[ModelBreakdown]
