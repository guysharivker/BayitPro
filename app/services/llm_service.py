import json
import logging
from dataclasses import dataclass

from app.config import ANTHROPIC_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS
from app.models import TicketCategory, TicketStatus, TicketUrgency
from app.services.llm_prompts import build_classification_prompt, build_daily_summary_prompt
from app.services.message_parser import (
    classify_category,
    extract_building_text,
    extract_supplier_status,
    extract_ticket_reference_number,
)

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:
    anthropic = None


@dataclass
class LLMClassification:
    category: TicketCategory
    urgency: TicketUrgency
    building_id: int | None
    building_reference: str | None
    is_status_update: bool
    new_status: TicketStatus | None
    ticket_reference: str | None
    summary: str


def _parse_category(raw: str) -> TicketCategory:
    try:
        return TicketCategory(raw.upper())
    except ValueError:
        return TicketCategory.GENERAL


def _parse_urgency(raw: str) -> TicketUrgency:
    try:
        return TicketUrgency(raw.upper())
    except ValueError:
        return TicketUrgency.MEDIUM


def _parse_status(raw: str | None) -> TicketStatus | None:
    if not raw:
        return None
    try:
        return TicketStatus(raw.upper())
    except ValueError:
        return None


def _parse_ticket_ref(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip() or None


def _parse_llm_response(raw_text: str) -> LLMClassification:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)

    return LLMClassification(
        category=_parse_category(data.get("category", "GENERAL")),
        urgency=_parse_urgency(data.get("urgency", "MEDIUM")),
        building_id=data.get("building_id"),
        building_reference=data.get("building_reference"),
        is_status_update=bool(data.get("is_status_update", False)),
        new_status=_parse_status(data.get("new_status")),
        ticket_reference=_parse_ticket_ref(data.get("ticket_reference")),
        summary=data.get("summary", ""),
    )


async def classify_message(
    text: str,
    known_buildings: list[dict],
    conversation_history: list[dict] | None = None,
) -> LLMClassification:
    if anthropic is None:
        logger.info("anthropic package is not installed, falling back to regex classification")
        return _fallback_classify(text)

    if not ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY set, falling back to regex classification")
        return _fallback_classify(text)

    try:
        client = anthropic.AsyncAnthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=LLM_TIMEOUT_SECONDS,
        )

        system_prompt = build_classification_prompt(known_buildings)

        # Build messages with conversation context
        messages = []
        if conversation_history:
            for msg in conversation_history[-5:]:  # Last 5 messages for context
                role = "user" if msg.get("direction") == "INBOUND" else "assistant"
                if role == "assistant":
                    # Wrap outbound messages as context
                    messages.append({"role": "user", "content": f"[הודעת מערכת קודמת: {msg['text']}]"})
                else:
                    messages.append({"role": "user", "content": msg["text"]})

        # Ensure alternating roles - collapse consecutive user messages
        collapsed = []
        for msg in messages:
            if collapsed and collapsed[-1]["role"] == msg["role"]:
                collapsed[-1]["content"] += "\n" + msg["content"]
            else:
                collapsed.append(msg)

        # Add current message
        if collapsed and collapsed[-1]["role"] == "user":
            collapsed[-1]["content"] += "\n---\nהודעה נוכחית לסיווג:\n" + text
        else:
            collapsed.append({"role": "user", "content": text})

        response = await client.messages.create(
            model=LLM_MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=collapsed,
        )

        raw_response = response.content[0].text
        return _parse_llm_response(raw_response)

    except Exception as exc:
        logger.warning("LLM classification failed (%s), falling back to regex", exc)
        return _fallback_classify(text)


async def generate_daily_summary(
    area_name: str,
    date: str,
    open_tickets: int,
    new_tickets_today: int,
    closed_today: int,
    sla_breached: int,
    in_progress: int,
    tickets_details: str,
    cleaning_status: str,
) -> str:
    if anthropic is None or not ANTHROPIC_API_KEY:
        return _fallback_daily_summary(
            area_name, open_tickets, new_tickets_today, closed_today, sla_breached
        )

    try:
        client = anthropic.AsyncAnthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=15,
        )

        prompt = build_daily_summary_prompt(
            area_name=area_name,
            date=date,
            open_tickets=open_tickets,
            new_tickets_today=new_tickets_today,
            closed_today=closed_today,
            sla_breached=sla_breached,
            in_progress=in_progress,
            tickets_details=tickets_details,
            cleaning_status=cleaning_status,
        )

        response = await client.messages.create(
            model=LLM_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text.strip()

    except Exception as exc:
        logger.warning("LLM daily summary failed (%s), using fallback", exc)
        return _fallback_daily_summary(
            area_name, open_tickets, new_tickets_today, closed_today, sla_breached
        )


def _fallback_daily_summary(
    area_name: str,
    open_tickets: int,
    new_tickets_today: int,
    closed_today: int,
    sla_breached: int,
) -> str:
    lines = [f"סיכום יומי - {area_name}:"]
    lines.append(f"קריאות פתוחות: {open_tickets}")
    if new_tickets_today > 0:
        lines.append(f"קריאות חדשות היום: {new_tickets_today}")
    if closed_today > 0:
        lines.append(f"נסגרו היום: {closed_today}")
    if sla_breached > 0:
        lines.append(f"⚠ {sla_breached} חריגות SLA - דורש טיפול מיידי!")
    return "\n".join(lines)


def _fallback_classify(text: str) -> LLMClassification:
    category = classify_category(text)
    building_ref = extract_building_text(text)
    supplier_status = extract_supplier_status(text)
    ticket_ref_num = extract_ticket_reference_number(text)

    ticket_ref = None
    if ticket_ref_num is not None:
        ticket_ref = f"#{ticket_ref_num}"

    return LLMClassification(
        category=category,
        urgency=TicketUrgency.MEDIUM,
        building_id=None,
        building_reference=building_ref,
        is_status_update=supplier_status is not None,
        new_status=supplier_status,
        ticket_reference=ticket_ref,
        summary=text[:100],
    )
