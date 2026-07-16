import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict, Any
from core.database import SessionLocal
from models.models import Account, AccountMember, Invite
from schemas.schemas import (
    AccountCreate, AccountOut, InviteCreate, InviteOut, 
    MemberOut, MemberUpdate, UserAccountInfo
)
from shared.messaging import RabbitMQClient

router = APIRouter(prefix="/accounts", tags=["accounts"])
rabbitmq = RabbitMQClient()

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
        return None
    return uuid.UUID(x_account_id)

def get_user_role(x_user_role: str = Header(None)):
    return x_user_role

@router.post("/create-team", response_model=AccountOut)
async def create_team(
    payload: AccountCreate, 
    user_id: uuid.UUID = Depends(get_user_id), 
    db: AsyncSession = Depends(get_db)
):
    """
    Explicit team creation flow. Creates a 'team' Account and registers user as 'owner'.
    """
    account = Account(
        name=payload.name,
        type="team",
        plan_tier="free" # starts on free tier
    )
    db.add(account)
    await db.flush()

    member = AccountMember(
        account_id=account.id,
        user_id=user_id,
        role="owner"
    )
    db.add(member)
    await db.commit()

    # Emit account.created event
    try:
        await rabbitmq.publish(
            exchange_name="user_events",
            routing_key="account.created",
            body={
                "account_id": str(account.id),
                "name": account.name,
                "type": account.type,
                "owner_id": str(user_id)
            }
        )
    except Exception as e:
        # log error
        pass

    return account

@router.get("/switch", response_model=List[UserAccountInfo])
async def list_user_accounts(
    user_id: uuid.UUID = Depends(get_user_id), 
    db: AsyncSession = Depends(get_db)
):
    """
    Get all accounts a user belongs to. Used for the account switcher dropdown.
    """
    query = (
        select(AccountMember.role, Account.id, Account.name, Account.type, Account.plan_tier)
        .join(Account, AccountMember.account_id == Account.id)
        .where(AccountMember.user_id == user_id)
    )
    result = await db.execute(query)
    
    accounts = []
    for row in result.all():
        accounts.append({
            "account_id": row.id,
            "name": row.name,
            "role": row.role,
            "type": row.type,
            "plan_tier": row.plan_tier
        })
    return accounts

@router.get("/profile", response_model=AccountOut)
async def get_account_profile(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Get general workspace info.
    """
    if not account_id:
        raise HTTPException(status_code=400, detail="Account context required")
    q = select(Account).where(Account.id == account_id)
    res = await db.execute(q)
    account = res.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return account

@router.post("/invite", response_model=InviteOut)
async def create_invite(
    payload: InviteCreate,
    user_id: uuid.UUID = Depends(get_user_id),
    account_id: uuid.UUID = Depends(get_account_id),
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Invite a user to a team. Restricted to owners/admins.
    """
    if not account_id:
        raise HTTPException(status_code=400, detail="Account context required")
    if role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Only owners and admins can invite members")

    # Generate invite details
    invite_token = str(uuid.uuid4())
    expires = datetime.datetime.utcnow() + datetime.timedelta(days=7)

    invite = Invite(
        account_id=account_id,
        email=payload.email,
        role=payload.role,
        token=invite_token,
        expires_at=expires
    )
    db.add(invite)
    await db.commit()

    # Emit invite created event for Notification Service to email the invitee
    try:
        await rabbitmq.publish(
            exchange_name="user_events",
            routing_key="member.invited",
            body={
                "invite_id": str(invite.id),
                "account_id": str(account_id),
                "email": payload.email,
                "role": payload.role,
                "token": invite_token
            }
        )
    except Exception as e:
        pass

    return invite

@router.post("/invite/accept")
async def accept_invite(
    payload: Dict[str, str],
    user_id: uuid.UUID = Depends(get_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Accept invite and add user to account.
    """
    token = payload.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    q = select(Invite).where(Invite.token == token, Invite.status == "pending")
    res = await db.execute(q)
    invite = res.scalar_one_or_none()

    if not invite or invite.expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired invite")

    # Mark invite as accepted
    invite.status = "accepted"

    # Add member
    member = AccountMember(
        account_id=invite.account_id,
        user_id=user_id,
        role=invite.role
    )
    db.add(member)
    await db.commit()

    # Emit member.joined
    try:
        await rabbitmq.publish(
            exchange_name="user_events",
            routing_key="member.joined",
            body={
                "account_id": str(invite.account_id),
                "user_id": str(user_id),
                "role": invite.role
            }
        )
    except Exception as e:
        pass

    return {"status": "invite accepted", "account_id": invite.account_id}

@router.get("/members", response_model=List[MemberOut])
async def list_members(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    List members of active account context.
    """
    if not account_id:
        raise HTTPException(status_code=400, detail="Account context required")
    q = select(AccountMember).where(AccountMember.account_id == account_id)
    res = await db.execute(q)
    return res.scalars().all()

@router.delete("/members/{member_id}")
async def remove_member(
    member_id: uuid.UUID,
    role: str = Depends(get_user_role),
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove member from account. Restricted to owner/admin.
    """
    if role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Only owners and admins can remove members")
    
    q = select(AccountMember).where(AccountMember.id == member_id, AccountMember.account_id == account_id)
    res = await db.execute(q)
    member = res.scalar_one_or_none()
    
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
        
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove owner of workspace")

    await db.delete(member)
    await db.commit()
    return {"status": "member removed"}

# INTERNAL ROUTE FOR AUTH SERVICE
@router.get("/internal/users/{user_id}/accounts", response_model=List[UserAccountInfo])
async def internal_get_user_accounts(
    user_id: uuid.UUID, 
    db: AsyncSession = Depends(get_db)
):
    """
    Internal API endpoint queried by Auth Service during token issuance.
    """
    query = (
        select(AccountMember.role, Account.id, Account.name, Account.type, Account.plan_tier)
        .join(Account, AccountMember.account_id == Account.id)
        .where(AccountMember.user_id == user_id)
    )
    result = await db.execute(query)
    
    accounts = []
    for row in result.all():
        accounts.append({
            "account_id": row.id,
            "name": row.name,
            "role": row.role,
            "type": row.type,
            "plan_tier": row.plan_tier
        })
    return accounts

@router.get("/admin/all", response_model=List[AccountOut])
async def admin_list_all_accounts(
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    List all accounts on the platform. Restricted to superadmin.
    """
    if role != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin privileges required")
    q = select(Account).order_by(Account.created_at.desc())
    res = await db.execute(q)
    return res.scalars().all()

