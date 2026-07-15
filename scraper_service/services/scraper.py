import os
import json
import logging
import asyncio
import uuid
import redis
from datetime import datetime
from typing import Dict, Any
import httpx
import urllib.parse
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
import motor.motor_asyncio
from shared.messaging import RabbitMQClient
from playwright.async_api import async_playwright

logger = logging.getLogger("scraper_service.worker")

# MongoDB connection helpers
async def get_mongo_db():
    user = os.getenv("MONGO_USER", "mongo_admin")
    password = os.getenv("MONGO_PASS", "mongo_secure_pass_2026")
    host = os.getenv("MONGO_HOST", "mongodb")
    port = os.getenv("MONGO_PORT", "27017")
    
    uri = f"mongodb://{user}:{password}@{host}:{port}/?authSource=admin"
    client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    return client["scraper_db"]

async def is_scraping_allowed(url: str) -> bool:
    """Check robots.txt guidelines for the target URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(robots_url, timeout=3.0)
            if resp.status_code == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                return rp.can_fetch("*", url)
    except Exception as e:
        logger.warning(f"Could not parse robots.txt for {url}: {e}. Defaulting to allowed.")
    return True

async def check_domain_rate_limit(url: str):
    """Enforce domain-level rate limiting using a shared Redis key."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    if not domain:
        return
        
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    # Check rate limit (1 request per 3 seconds per domain)
    try:
        with redis.Redis(host=redis_host, port=redis_port, decode_responses=True) as r:
            key = f"scraper:rate_limit:{domain}"
            while r.get(key):
                logger.info(f"Rate limit hit for domain '{domain}'. Waiting 1 second...")
                await asyncio.sleep(1.0)
            # Reserve domain slot for 3s
            r.set(key, "1", ex=3)
    except Exception as e:
        logger.warning(f"Redis rate limit check error: {e}. Skipping limit check.")

async def perform_scrape_playwright(url: str) -> Dict[str, Any]:
    """Scrape utilizing Playwright headless browser to run client JS."""
    async with async_playwright() as p:
        # Launch chromium
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_extra_http_headers({"User-Agent": "CreditFlowCrawler/1.0"})
            
            resp = await page.goto(url, wait_until="networkidle", timeout=20000)
            status_code = resp.status if resp else 200
            
            content = await page.content()
            title = await page.title()
            text = await page.locator("body").inner_text()
            
            return {
                "title": title.strip() if title else "Untitled",
                "url": url,
                "raw_html": content,
                "text": text.strip(),
                "status_code": status_code
            }
        finally:
            await browser.close()

async def perform_scrape_fallback(url: str) -> Dict[str, Any]:
    """Fallback static HTTP scraper if Playwright setup is not initialized."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows; CreditFlowScraper/1.0)"
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code != 200:
            raise Exception(f"Static HTTP GET failed with status code {resp.status_code}")
            
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        
        # Strip script and style tags
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()
            
        title = soup.title.string if soup.title else ""
        text = soup.get_text(separator="\n")
        
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = "\n".join(chunk for chunk in chunks if chunk)
        
        return {
            "title": title.strip() if title else "Untitled",
            "url": url,
            "raw_html": html,
            "text": clean_text,
            "status_code": resp.status_code
        }

async def perform_scrape(url: str) -> Dict[str, Any]:
    """Attempts Playwright browser scrape, with static HTTPX fallback on failure."""
    try:
        logger.info(f"Attempting Playwright browser scrape for {url}")
        return await perform_scrape_playwright(url)
    except Exception as e:
        logger.warning(f"Playwright scrape failed ({e}). Falling back to static HTTP parsing.")
        return await perform_scrape_fallback(url)

async def handle_scrape_request(event_body: Dict[str, Any], event_id: str):
    """
    Consumer task that checks domain rate limits, respects robots.txt, 
    executes crawlers, and stores outcomes in MongoDB.
    """
    url = event_body.get("url")
    job_id = event_body.get("job_id", str(uuid.uuid4()))
    account_id = event_body.get("account_id")
    
    if not url:
        logger.error("Scrape requested event missing URL.")
        return

    rabbitmq = RabbitMQClient()
    
    # 1. Enforce domain rate limit
    await check_domain_rate_limit(url)
    
    # 2. Respect Robots.txt
    allowed = await is_scraping_allowed(url)
    if not allowed:
        logger.warning(f"Scraping {url} blocked by robots.txt rules.")
        await rabbitmq.publish(
            exchange_name="scraper_events",
            routing_key="scrape.failed",
            body={"job_id": job_id, "url": url, "reason": "Blocked by robots.txt rules"},
            event_id=event_id
        )
        return

    # 3. Run scraping
    try:
        scraped_data = await perform_scrape(url)
        scraped_data["job_id"] = job_id
        scraped_data["account_id"] = account_id
        scraped_data["scraped_at"] = datetime.utcnow().isoformat()
        
        # Store to MongoDB
        db = await get_mongo_db()
        result = await db.scraped_documents.insert_one(scraped_data)
        mongo_id = str(result.inserted_id)
        logger.info(f"Scraped document saved to MongoDB ID {mongo_id}")
        
        # Emit completed
        await rabbitmq.publish(
            exchange_name="scraper_events",
            routing_key="scrape.completed",
            body={
                "job_id": job_id,
                "url": url,
                "mongo_id": mongo_id,
                "title": scraped_data["title"]
            },
            event_id=event_id
        )
    except Exception as e:
        logger.error(f"Scraping task execution failed: {e}")
        await rabbitmq.publish(
            exchange_name="scraper_events",
            routing_key="scrape.failed",
            body={"job_id": job_id, "url": url, "reason": str(e)},
            event_id=event_id
        )

async def start_consumer():
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in scraper consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("scraper_service_queue")
    scraper_ex = await rabbitmq.declare_exchange("scraper_events")
    await queue.bind(scraper_ex, routing_key="scrape.requested")

    logger.info("Scraper Service background event consumer started.")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    payload = json.loads(message.body.decode())
                    event_id = payload["event_id"]
                    routing_key = payload["routing_key"]
                    body = payload["body"]
                    
                    logger.info(f"Scraper consumer received event: {routing_key} ({event_id})")
                    
                    if routing_key == "scrape.requested":
                        await handle_scrape_request(body, event_id)
                except Exception as e:
                    logger.error(f"Error handling scraper queue event: {e}", exc_info=True)
