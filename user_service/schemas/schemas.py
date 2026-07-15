import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr

class AccountCreate(BaseModel):
    name: str

class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    plan_tier: str
    created_at: datetime

    class Config:
        from_attributes = True

class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "member"

class InviteOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    email: EmailStr
    role: str
    status: str
    expires_at: datetime

    class Config:
        from_attributes = True

class MemberOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    created_at: datetime

    class Config:
        from_attributes = True

class MemberUpdate(BaseModel):
    role: str

class UserAccountInfo(BaseModel):
    account_id: uuid.UUID
    name: str
    role: str
    type: str
    plan_tier: str
