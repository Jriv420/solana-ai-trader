import httpx
from config.settings import settings
async def ask_darwin(prompt,data):
    if not settings.darwin_api_key or not settings.darwin_endpoint: raise RuntimeError("Darwin not configured")
    async with httpx.AsyncClient(timeout=settings.darwin_timeout_ms/1000) as c:
        r=await c.post(settings.darwin_endpoint,json={"prompt":prompt,"data":data},
                       headers={"Authorization":f"Bearer {settings.darwin_api_key}"})
        r.raise_for_status(); return r.json()
