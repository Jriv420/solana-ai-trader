import httpx
from config.settings import settings
async def ask_jev(state,questions):
    if not settings.jev_api_key or not settings.jev_endpoint: raise RuntimeError("Jev not configured")
    async with httpx.AsyncClient(timeout=settings.jev_timeout_ms/1000) as c:
        r=await c.post(settings.jev_endpoint,json={"state":state,"questions":questions},
                       headers={"Authorization":f"Bearer {settings.jev_api_key}"})
        r.raise_for_status(); return r.json()
