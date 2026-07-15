import uuid
from fastapi import APIRouter, Depends, HTTPException, Header, status
from typing import List, Dict, Any
from pydantic import BaseModel, HttpUrl

from services.scraper import get_mongo_db
from shared.messaging import RabbitMQClient

router = APIRouter(prefix="/scraper", tags=["scraper"])
rabbitmq = RabbitMQClient()

# Helper dependencies to extract gateway headers
def get_user_id(x_user_id: str = Header(None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header missing")
    return uuid.UUID(x_user_id)

def get_account_id(x_account_id: str = Header(None)):
    if not x_account_id:
        raise HTTPException(status_code=400, detail="X-Account-Id header missing")
    return uuid.UUID(x_account_id)

class ScrapeRequest(BaseModel):
    url: str

@router.post("/scrape", status_code=status.HTTP_202_ACCEPTED)
async def request_scrape(
    payload: ScrapeRequest,
    account_id: uuid.UUID = Depends(get_account_id)
):
    """
    Publish web scraping request to RabbitMQ worker queue.
    """
    job_id = str(uuid.uuid4())
    
    # Emit event
    await rabbitmq.publish(
        exchange_name="scraper_events",
        routing_key="scrape.requested",
        body={
            "job_id": job_id,
            "url": payload.url,
            "account_id": str(account_id)
        }
    )
    
    return {"status": "scraping_queued", "job_id": job_id}

@router.get("/results", response_model=List[Dict[str, Any]])
async def list_scrape_results(
    account_id: uuid.UUID = Depends(get_account_id)
):
    """
    Fetch all crawled documents from MongoDB for this workspace.
    """
    db = await get_mongo_db()
    cursor = db.scraped_documents.find({"account_id": str(account_id)})
    
    results = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"]) # stringify ObjectID
        results.append(doc)
    return results

@router.get("/results/{job_id}", response_model=Dict[str, Any])
async def get_scrape_result(
    job_id: str,
    account_id: uuid.UUID = Depends(get_account_id)
):
    """
    Get crawl result by Job ID.
    """
    db = await get_mongo_db()
    doc = await db.scraped_documents.find_one({"job_id": job_id, "account_id": str(account_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Scrape result not found or still processing")
    doc["_id"] = str(doc["_id"])
    return doc
