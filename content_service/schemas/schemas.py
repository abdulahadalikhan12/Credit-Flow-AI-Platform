import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class ContentCreate(BaseModel):
    title: str
    body: str
    image_url: Optional[str] = None

class ContentUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    image_url: Optional[str] = None
    status: Optional[str] = None # draft, approved, published

class ContentOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    title: str
    body: str
    image_url: Optional[str]
    status: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ContentVersionOut(BaseModel):
    id: uuid.UUID
    content_id: uuid.UUID
    body: str
    image_url: Optional[str]
    version: int
    created_by: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True
