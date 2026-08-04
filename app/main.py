from app.gamdlapi import get_any_url
from fastapi import FastAPI
import asyncio
from pydantic import BaseModel

class URLRequest(BaseModel):
    url: str

app = FastAPI()

@app.post("/web/getMetadata")
async def test(url: URLRequest):
    return await get_any_url(url.url)
