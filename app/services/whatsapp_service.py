import base64
import ssl
from urllib import parse, request
from urllib.error import HTTPError, URLError

import certifi
from sqlalchemy.orm import Session

from app.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
from app.models import Message, MessageDirection


def _normalize_twilio_whatsapp_to(phone_number: str) -> str:
    cleaned = phone_number.strip()
    if cleaned.startswith("whatsapp:"):
        return cleaned
    return f"whatsapp:{cleaned}"


def _try_send_via_twilio(phone_number: str, text: str, from_number: str | None = None) -> None:
    account_sid = TWILIO_ACCOUNT_SID
    auth_token = TWILIO_AUTH_TOKEN
    from_whatsapp = from_number or TWILIO_WHATSAPP_FROM

    if not account_sid or not auth_token or not from_whatsapp:
        print("[MOCK WHATSAPP OUTBOUND] Twilio credentials missing, using local mock only.")
        return

    payload = parse.urlencode(
        {
            "From": _normalize_twilio_whatsapp_to(from_whatsapp),
            "To": _normalize_twilio_whatsapp_to(phone_number),
            "Body": text,
        }
    ).encode("utf-8")
    twilio_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    auth_bytes = f"{account_sid}:{auth_token}".encode("utf-8")
    auth_header = base64.b64encode(auth_bytes).decode("utf-8")

    req = request.Request(twilio_url, data=payload, method="POST")
    req.add_header("Authorization", f"Basic {auth_header}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with request.urlopen(req, timeout=10, context=ssl_context) as response:
            print(f"[TWILIO OUTBOUND] status={response.status} to={phone_number} from={from_whatsapp} text={text}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(f"[TWILIO OUTBOUND ERROR] status={exc.code} to={phone_number} body={body}")
    except URLError as exc:
        print(f"[TWILIO OUTBOUND ERROR] to={phone_number} reason={exc.reason}")


def send_whatsapp_message(
    db: Session,
    phone_number: str,
    text: str,
    ticket_id: int | None = None,
    sender_role: str = "SYSTEM",
    from_number: str | None = None,
) -> Message:
    _try_send_via_twilio(phone_number=phone_number, text=text, from_number=from_number)
    print(f"[OUTBOUND LOG] to={phone_number} ticket_id={ticket_id} text={text}")

    message = Message(
        direction=MessageDirection.OUTBOUND,
        phone_number=phone_number,
        receiving_number=from_number,
        sender_role=sender_role,
        raw_text=text,
        ticket_id=ticket_id,
    )
    db.add(message)
    db.flush()
    return message
