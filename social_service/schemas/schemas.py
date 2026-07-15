import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class ConnectionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    platform: str
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True

class JobOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    content_id: uuid.UUID
    platform: str
    status: str
    post_url: Optional[str]
    error_reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
