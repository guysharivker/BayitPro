from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import ENV
from app.db import SessionLocal, get_db, reset_database
from app.schemas import SeedResponse, WebhookPayload, WebhookResponse
from app.services.notifier import broadcast_ticket_event
from app.services.seed_service import seed_data
from app.services.ticket_service import process_inbound_whatsapp_message

router = APIRouter(tags=["webhook"])


@router.post("/webhook/whatsapp", response_model=WebhookResponse)
async def whatsapp_webhook(payload: WebhookPayload, db: Session = Depends(get_db)) -> WebhookResponse:
    result = await process_inbound_whatsapp_message(db, payload)
    await broadcast_ticket_event(result["action_taken"], result)
    return WebhookResponse(**result)


def _normalize_twilio_from(from_value: str) -> str:
    normalized = from_value.strip()
    if normalized.startswith("whatsapp:"):
        normalized = normalized.split("whatsapp:", maxsplit=1)[1]
    return normalized


@router.post("/webhook/twilio")
async def twilio_webhook(
    from_phone: str = Form(..., alias="From"),
    to_phone: str = Form(default="", alias="To"),
    body: str = Form(default="", alias="Body"),
    media_url_0: str | None = Form(default=None, alias="MediaUrl0"),
    db: Session = Depends(get_db),
) -> Response:
    receiving_number = _normalize_twilio_from(to_phone) if to_phone else None

    payload = WebhookPayload(
        phone_number=_normalize_twilio_from(from_phone),
        text=body,
        image_url=media_url_0,
        timestamp=datetime.now(UTC).replace(tzinfo=None),
        receiving_number=receiving_number,
    )
    result = await process_inbound_whatsapp_message(db, payload)
    await broadcast_ticket_event(result["action_taken"], result)
    return Response(content="<Response></Response>", media_type="application/xml")


@router.post("/seed", response_model=SeedResponse)
def seed(
    reset: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> SeedResponse:
    if ENV != "development":
        raise HTTPException(status_code=403, detail="Seed endpoint is only available in development")
    if not reset:
        result = seed_data(db)
        return SeedResponse(**result)

    db.close()
    reset_database()

    fresh_db = SessionLocal()
    try:
        result = seed_data(fresh_db)
        return SeedResponse(**result)
    finally:
        fresh_db.close()
