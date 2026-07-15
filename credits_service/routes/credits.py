import uuid
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List

from core.database import SessionLocal
from models.models import CreditLedgerEntry, MarketplaceListing
from schemas.schemas import BalanceResponse, ListingCreate, ListingOut
from shared.messaging import RabbitMQClient

router = APIRouter(prefix="/credits", tags=["credits"])
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
        raise HTTPException(status_code=400, detail="X-Account-Id header missing")
    return uuid.UUID(x_account_id)

def get_user_role(x_user_role: str = Header(None)):
    return x_user_role

async def calculate_balance(session: AsyncSession, account_id: uuid.UUID) -> int:
    """Helper to sum ledger entries and return balance."""
    q = select(func.sum(CreditLedgerEntry.amount)).where(CreditLedgerEntry.account_id == account_id)
    res = await session.execute(q)
    balance = res.scalar()
    return balance if balance is not None else 0

@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the credit balance and transaction ledger for the active workspace.
    """
    balance = await calculate_balance(db, account_id)
    
    q = select(CreditLedgerEntry).where(CreditLedgerEntry.account_id == account_id).order_by(CreditLedgerEntry.created_at.desc())
    res = await db.execute(q)
    ledger = res.scalars().all()
    
    return {"balance": balance, "ledger": ledger}

@router.post("/marketplace/list", response_model=ListingOut)
async def create_listing(
    payload: ListingCreate,
    account_id: uuid.UUID = Depends(get_account_id),
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    List surplus credits for sale. Placed in escrow.
    """
    if role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Only owners and admins can manage marketplace listings")

    # Start an explicit database transaction
    async with db.begin():
        # 1. Verify sufficient balance
        balance = await calculate_balance(db, account_id)
        if balance < payload.amount:
            raise HTTPException(status_code=400, detail="Insufficient credits to list on marketplace")
            
        # 2. Add ledger entry to debit/escrow credits
        escrow_entry = CreditLedgerEntry(
            account_id=account_id,
            amount=-payload.amount,
            transaction_type="transfer_out",
            description="Marketplace listing escrow"
        )
        db.add(escrow_entry)

        # 3. Create marketplace listing
        listing = MarketplaceListing(
            seller_account_id=account_id,
            amount=payload.amount,
            price=payload.price,
            status="active"
        )
        db.add(listing)
    return listing

@router.get("/marketplace/listings", response_model=List[ListingOut])
async def get_active_listings(
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch all active credit listings available for purchase.
    """
    q = select(MarketplaceListing).where(MarketplaceListing.status == "active").order_by(MarketplaceListing.created_at.desc())
    res = await db.execute(q)
    return res.scalars().all()

@router.post("/marketplace/buy/{listing_id}")
async def buy_listing(
    listing_id: uuid.UUID,
    buyer_account_id: uuid.UUID = Depends(get_account_id),
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Purchase a credit listing. Deducts from buyer's account and updates seller's ledger.
    """
    if role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Only owners and admins can purchase credits")

    async with db.begin():
        # 1. Fetch listing and lock row for safety
        q = select(MarketplaceListing).where(MarketplaceListing.id == listing_id).with_for_update()
        res = await db.execute(q)
        listing = res.scalar_one_or_none()
        
        if not listing:
            raise HTTPException(status_code=404, detail="Listing not found")
        if listing.status != "active":
            raise HTTPException(status_code=400, detail="Listing is no longer active")
        if listing.seller_account_id == buyer_account_id:
            raise HTTPException(status_code=400, detail="Cannot purchase your own listing")
            
        # 2. Update listing status
        listing.status = "sold"
        
        # 3. Credit Buyer
        buyer_entry = CreditLedgerEntry(
            account_id=buyer_account_id,
            amount=listing.amount,
            transaction_type="transfer_in",
            description=f"Marketplace purchase from {listing.seller_account_id}"
        )
        db.add(buyer_entry)
        
        # 4. In a real billing gateway, money would transfer here. 
        # For simulation, the seller receives cash payout (simulated) and their escrow is already deducted.
        # Seller gets confirmation.
    
    # Emit events
    try:
        await rabbitmq.publish(
            exchange_name="credits_events",
            routing_key="credits.credited",
            body={
                "account_id": str(buyer_account_id),
                "amount": listing.amount,
                "reason": "marketplace_purchase"
            }
        )
        await rabbitmq.publish(
            exchange_name="credits_events",
            routing_key="credits.debited",
            body={
                "account_id": str(listing.seller_account_id),
                "amount": listing.amount,
                "reason": "marketplace_sold"
            }
        )
    except Exception:
        pass

    return {"status": "success", "amount": listing.amount}
