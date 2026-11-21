import logging
import os
from hmac import compare_digest

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
log = logging.getLogger(__name__)


def authorize(provided: str, env_var: str, prefix: str = "") -> None:
    secret = os.getenv(env_var, "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Service is not configured")
    if not compare_digest(provided.encode(), (prefix + secret).encode()):
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/telegram")
async def telegram(request: Request) -> dict[str, bool]:
    authorize(request.headers.get("x-telegram-bot-api-secret-token", ""), "TELEGRAM_WEBHOOK_SECRET")
    try:
        update = Update.model_validate_json(await request.body())
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid Telegram update") from None

    try:
        from webhook import handle_update

        await handle_update(update)
    except Exception as exc:
        log.error("Telegram update %s failed: %s", update.update_id, type(exc).__name__)
        raise HTTPException(status_code=503, detail="Update temporarily unavailable") from None
    return {"ok": True}


@app.get("/api/cron")
async def cron(request: Request) -> dict[str, bool]:
    authorize(request.headers.get("authorization", ""), "CRON_SECRET", prefix="Bearer ")
    try:
        from webhook import run_daily_jobs

        await run_daily_jobs()
    except Exception as exc:
        log.error("Daily jobs failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Daily jobs temporarily unavailable") from None
    return {"ok": True}
