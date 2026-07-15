import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class GenerateRequest(BaseModel):
    prompt: str
    model: Optional[str] = "gemini" # gemini, llama, mistral

class GenerateResponse(BaseModel):
    job_id: str

class ImageGenerateRequest(BaseModel):
    prompt: str
    model: Optional[str] = "flux" # flux, turbo, anime

class ImageGenerateResponse(BaseModel):
    image_url: str

class HistoryOut(BaseModel):
    id: uuid.UUID
    prompt: str
    response: str
    tokens_used: int
    cost: int
    model: str
    created_at: datetime

    class Config:
        from_attributes = True
