import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class ScheduleRequest(BaseModel):
    content_id: uuid.UUID
    publish_at: datetime # in UTC
    repeat_cadence: Optional[str] = "none" # none, daily, weekly, monthly

class ScheduledPostOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    content_id: uuid.UUID
    publish_at: datetime
    repeat_cadence: str
    status: str
    last_published_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
