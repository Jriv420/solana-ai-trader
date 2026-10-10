import httpx
from config.settings import settings
async def ask_laya(state,questions):
    if not settings.laya_api_key or not settings.laya_endpoint: raise RuntimeError("Laya not configured")
    async with httpx.AsyncClient(timeout=settings.laya_timeout_ms/1000) as c:
        r=await c.post(settings.laya_endpoint,json={"state":state,"questions":questions},
                       headers={"Authorization":f"Bearer {settings.laya_api_key}"})
        r.raise_for_status(); return r.json()
