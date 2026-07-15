import uuid
import os
import logging
import shutil
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List, Dict, Any, Optional

from core.database import SessionLocal
from models.models import Content, ContentVersion
from schemas.schemas import ContentCreate, ContentUpdate, ContentOut, ContentVersionOut
from shared.messaging import RabbitMQClient

router = APIRouter(prefix="/content", tags=["content"])
rabbitmq = RabbitMQClient()
logger = logging.getLogger("content_service.routes")

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

def get_user_role(x_user_role: str = Header(None)):
    return x_user_role

@router.post("", response_model=ContentOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: ContentCreate,
    user_id: uuid.UUID = Depends(get_user_id),
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new draft post and write initial Version 1 record.
    """
    async with db.begin():
        # 1. Create content
        content = Content(
            account_id=account_id,
            title=payload.title,
            body=payload.body,
            image_url=payload.image_url,
            status="draft",
            created_by=user_id
        )
        db.add(content)
        await db.flush() # populate content.id

        # 2. Save version 1
        version = ContentVersion(
            content_id=content.id,
            body=content.body,
            image_url=content.image_url,
            version=1,
            created_by=user_id
        )
        db.add(version)

    # Emit event
    try:
        await rabbitmq.publish(
            exchange_name="content_events",
            routing_key="content.created",
            body={
                "content_id": str(content.id),
                "account_id": str(account_id),
                "title": content.title,
                "status": content.status
            }
        )
    except Exception as e:
        logger.error(f"Event publish failed: {e}")

    return content

@router.get("", response_model=List[ContentOut])
async def list_posts(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    List posts belonging to the workspace.
    """
    q = select(Content).where(Content.account_id == account_id).order_by(Content.created_at.desc())
    res = await db.execute(q)
    return res.scalars().all()

@router.get("/{content_id}", response_model=ContentOut)
async def get_post(
    content_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve single post details.
    """
    q = select(Content).where(Content.id == content_id, Content.account_id == account_id)
    res = await db.execute(q)
    content = res.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    return content

@router.put("/{content_id}", response_model=ContentOut)
async def update_post(
    content_id: uuid.UUID,
    payload: ContentUpdate,
    user_id: uuid.UUID = Depends(get_user_id),
    account_id: uuid.UUID = Depends(get_account_id),
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Update post details. Tracks version history.
    Enforces status updates to approved/published only for owner/admin roles.
    """
    async with db.begin():
        q = select(Content).where(Content.id == content_id, Content.account_id == account_id).with_for_update()
        res = await db.execute(q)
        content = res.scalar_one_or_none()
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")

        # RBAC Check for status progression
        if payload.status and payload.status != content.status:
            if payload.status in ["approved", "published"] and role not in ["owner", "admin"]:
                raise HTTPException(status_code=403, detail="Only Owners or Admins can approve or publish content")
            
            valid_transitions = {
                "draft": ["approved"],
                "approved": ["published", "draft"],
                "published": ["draft"]
            }
            allowed_next = valid_transitions.get(content.status, [])
            if payload.status not in allowed_next:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid content status transition from '{content.status}' to '{payload.status}'. Allowed transitions: {allowed_next}"
                )
            content.status = payload.status

        # Update general fields
        if payload.title:
            content.title = payload.title

        is_body_changed = payload.body and payload.body != content.body
        is_image_changed = payload.image_url is not None and payload.image_url != content.image_url
        
        if is_body_changed or is_image_changed:
            if payload.body:
                content.body = payload.body
            if payload.image_url is not None:
                content.image_url = payload.image_url

            # Get current max version
            vq = select(func.max(ContentVersion.version)).where(ContentVersion.content_id == content_id)
            vres = await db.execute(vq)
            max_v = vres.scalar() or 0
            
            # Record new version
            new_version = ContentVersion(
                content_id=content_id,
                body=content.body,
                image_url=content.image_url,
                version=max_v + 1,
                created_by=user_id
            )
            db.add(new_version)

    # Emit event
    try:
        await rabbitmq.publish(
            exchange_name="content_events",
            routing_key="content.updated",
            body={
                "content_id": str(content.id),
                "account_id": str(account_id),
                "title": content.title,
                "status": content.status
            }
        )
    except Exception as e:
         pass

    return content

@router.delete("/{content_id}")
async def delete_post(
    content_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove content post from workspace.
    """
    q = select(Content).where(Content.id == content_id, Content.account_id == account_id)
    res = await db.execute(q)
    content = res.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
        
    await db.delete(content)
    await db.commit()
    return {"status": "deleted"}

@router.get("/{content_id}/versions", response_model=List[ContentVersionOut])
async def list_versions(
    content_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch history logs for a specific post.
    """
    # Verify content belongs to account
    q = select(Content).where(Content.id == content_id, Content.account_id == account_id)
    res = await db.execute(q)
    if not res.scalar_one_or_none():
         raise HTTPException(status_code=404, detail="Content not found")

    vq = select(ContentVersion).where(ContentVersion.content_id == content_id).order_by(ContentVersion.version.desc())
    vres = await db.execute(vq)
    return vres.scalars().all()

@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...)
):
    """
    Multipart file handler. Stores uploaded image to local storage volume.
    """
    uploads_dir = "/app/content_service/static/uploads"
    os.makedirs(uploads_dir, exist_ok=True)
    
    file_ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    dest_path = os.path.join(uploads_dir, unique_filename)
    
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Return path accessible via gateway static forwarding
    # Gateway routes /api/v1/content/* to content service, so static path fits perfectly:
    # http://localhost:8000/api/v1/content/static/uploads/{unique_filename}
    return {"image_url": f"/api/v1/content/static/uploads/{unique_filename}"}
