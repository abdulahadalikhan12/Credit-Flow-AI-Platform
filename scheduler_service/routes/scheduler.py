import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from core.database import SessionLocal
from models.models import ScheduledPost
from schemas.schemas import ScheduleRequest, ScheduledPostOut

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

async def get_db():
    async with SessionLocal() as session:
        yield session

# Helper dependencies to extract gateway headers
def get_user_id(x_user_id: str = Header(None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header missing")
    return uuid.UUID(x_user_id)

def get_account_id(x_account_id: str = Header(None)):
    if not x_account_id:
        raise HTTPException(status_code=400, detail="X-Account-Id header missing")
    return uuid.UUID(x_account_id)

@router.post("/schedule", response_model=ScheduledPostOut, status_code=status.HTTP_201_CREATED)
async def schedule_content(
    payload: ScheduleRequest,
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Schedule a draft content post for future publishing (one-off or recurring).
    """
    # Validate date is in the future
    # Need to compare offset-naive or offset-aware. We'll strip timezone if input is offset-aware
    target_time = payload.publish_at.replace(tzinfo=None)
    if target_time <= datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Publish date must be in the future")

    # Verify if already scheduled
    q_check = select(ScheduledPost).where(
        ScheduledPost.content_id == payload.content_id,
        ScheduledPost.status == "scheduled"
    )
    res_check = await db.execute(q_check)
    if res_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This content is already scheduled")

    scheduled_post = ScheduledPost(
        account_id=account_id,
        content_id=payload.content_id,
        publish_at=target_time,
        repeat_cadence=payload.repeat_cadence.lower(),
        status="scheduled"
    )
    
    db.add(scheduled_post)
    await db.commit()
    return scheduled_post

@router.get("/calendar", response_model=List[ScheduledPostOut])
async def get_calendar(
    start_date: datetime.date,
    end_date: datetime.date,
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Get scheduled posts within a specific date range for the calendar.
    """
    # Convert date to datetime bounds in UTC
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max)

    q = select(ScheduledPost).where(
        ScheduledPost.account_id == account_id,
        ScheduledPost.publish_at >= start_dt,
        ScheduledPost.publish_at <= end_dt
    ).order_by(ScheduledPost.publish_at.asc())
    
    res = await db.execute(q)
    return res.scalars().all()

@router.post("/cancel/{schedule_id}")
async def cancel_schedule(
    schedule_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel an active scheduled post.
    """
    q = select(ScheduledPost).where(
        ScheduledPost.id == schedule_id,
        ScheduledPost.account_id == account_id
    )
    res = await db.execute(q)
    post = res.scalar_one_or_none()
    
    if not post:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
        
    if post.status != "scheduled":
        raise HTTPException(status_code=400, detail="Only scheduled posts can be canceled")

    await db.delete(post)
    await db.commit()
    return {"status": "canceled"}

@router.post("/reschedule/{schedule_id}", response_model=ScheduledPostOut)
async def reschedule_post(
    schedule_id: uuid.UUID,
    publish_at: datetime.datetime,
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Reschedule an active post to a different time.
    """
    target_time = publish_at.replace(tzinfo=None)
    if target_time <= datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Publish date must be in the future")

    q = select(ScheduledPost).where(
        ScheduledPost.id == schedule_id,
        ScheduledPost.account_id == account_id
    )
    res = await db.execute(q)
    post = res.scalar_one_or_none()
    
    if not post:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
        
    if post.status != "scheduled":
        raise HTTPException(status_code=400, detail="Only active scheduled posts can be rescheduled")

    post.publish_at = target_time
    await db.commit()
    return post
