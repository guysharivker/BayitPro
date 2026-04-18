import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Area,
    Building,
    Contact,
    ContactRole,
    Message,
    MessageDirection,
    Supplier,
    Ticket,
    TicketCategory,
    TicketStatus,
    TicketUrgency,
)
from app.schemas import WebhookPayload
from app.services.llm_service import LLMClassification, classify_message
from app.services.whatsapp_service import send_whatsapp_message


SLA_HOURS_BY_CATEGORY: dict[TicketCategory, int] = {
    TicketCategory.CLEANING: 24,
    TicketCategory.ELECTRIC: 6,
    TicketCategory.PLUMBING: 4,
    TicketCategory.ELEVATOR: 2,
    TicketCategory.GENERAL: 24,
}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def compute_sla_due_at(category: TicketCategory, created_at: datetime) -> datetime:
    return created_at + timedelta(hours=SLA_HOURS_BY_CATEGORY[category])


def is_sla_breached(ticket: Ticket, now: datetime | None = None) -> bool:
    if not ticket.sla_due_at:
        return False

    comparison_time = now or utc_now()
    if ticket.status == TicketStatus.DONE:
        if not ticket.completed_at:
            return False
        return ticket.completed_at > ticket.sla_due_at

    return comparison_time > ticket.sla_due_at


def _normalize_address(address: str) -> str:
    return " ".join(address.strip().lower().split())


def _resolve_area(db: Session, receiving_number: str | None) -> Area | None:
    if receiving_number:
        cleaned = receiving_number.strip()
        if cleaned.startswith("whatsapp:"):
            cleaned = cleaned.split("whatsapp:", maxsplit=1)[1]
        match = db.query(Area).filter(Area.whatsapp_number == cleaned).first()
        if match:
            return match
    # Fallback: return first area so sandbox messages are always attributed
    return db.query(Area).order_by(Area.id.asc()).first()


def _get_area_buildings(db: Session, area: Area | None) -> list[Building]:
    if not area:
        return db.query(Building).all()
    return db.query(Building).filter(Building.area_id == area.id).all()


def _get_known_buildings_for_llm(buildings: list[Building]) -> list[dict]:
    return [{"id": b.id, "address_text": b.address_text, "name": b.name} for b in buildings]


def _get_conversation_history(db: Session, phone_number: str, limit: int = 10) -> list[dict]:
    messages = (
        db.query(Message)
        .filter(Message.phone_number == phone_number)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {"direction": m.direction.value, "text": m.raw_text, "created_at": str(m.created_at)}
        for m in reversed(messages)
    ]


def _find_building_by_id(db: Session, building_id: int, area: Area | None) -> Building | None:
    query = db.query(Building).filter(Building.id == building_id)
    if area:
        query = query.filter(Building.area_id == area.id)
    return query.first()


def _find_building_by_text(db: Session, building_text: str | None, area: Area | None) -> Building | None:
    if not building_text:
        return None

    normalized = _normalize_address(building_text)
    query = db.query(Building)
    if area:
        query = query.filter(Building.area_id == area.id)

    buildings = query.all()
    for building in buildings:
        address_normalized = _normalize_address(building.address_text)
        name_normalized = _normalize_address(building.name)
        if normalized in {address_normalized, name_normalized}:
            return building
        if normalized in address_normalized or address_normalized in normalized:
            return building
        if normalized in name_normalized or name_normalized in normalized:
            return building

    return None


def _find_supplier_for_category(db: Session, category: TicketCategory, area: Area | None) -> Supplier | None:
    if area:
        area_supplier = (
            db.query(Supplier)
            .filter(Supplier.category == category, Supplier.area_id == area.id)
            .first()
        )
        if area_supplier:
            return area_supplier

    return db.query(Supplier).filter(Supplier.category == category, Supplier.area_id.is_(None)).first()


def _get_ticket_by_reference(db: Session, reference: str, area: Area | None) -> Ticket | None:
    hash_match = re.search(r"#(\d+)", reference)
    if hash_match:
        ref_num = int(hash_match.group(1))
        by_id_query = db.query(Ticket).filter(Ticket.id == ref_num)
        if area:
            by_id_query = by_id_query.filter(Ticket.area_id == area.id)
        by_id = by_id_query.first()
        if by_id:
            return by_id
        public_id = f"TCK-{ref_num:04d}"
        public_query = db.query(Ticket).filter(Ticket.public_id == public_id)
        if area:
            public_query = public_query.filter(Ticket.area_id == area.id)
        return public_query.first()

    public_match = re.search(r"\bTCK-(\d+)\b", reference, flags=re.IGNORECASE)
    if public_match:
        ref_num = int(public_match.group(1))
        public_id = f"TCK-{ref_num:04d}"
        public_query = db.query(Ticket).filter(Ticket.public_id == public_id)
        if area:
            public_query = public_query.filter(Ticket.area_id == area.id)
        return public_query.first()

    return None


def _find_recent_open_ticket_for_sender_and_building(
    db: Session,
    sender_phone: str,
    building_text: str | None,
    building_id: int | None,
    now: datetime,
    area: Area | None,
) -> Ticket | None:
    time_window_start = now - timedelta(hours=48)

    base_query = (
        db.query(Ticket)
        .filter(Ticket.resident_phone == sender_phone)
        .filter(Ticket.status != TicketStatus.DONE)
        .filter(Ticket.created_at >= time_window_start)
    )
    if area:
        base_query = base_query.filter(Ticket.area_id == area.id)

    # Try exact building_id match first (from LLM fuzzy matching)
    if building_id:
        match = base_query.filter(Ticket.building_id == building_id).order_by(Ticket.created_at.desc()).first()
        if match:
            return match

    # Fall back to text matching
    if building_text:
        building_normalized = _normalize_address(building_text)
        matches = base_query.order_by(Ticket.created_at.desc()).all()
        for ticket in matches:
            candidate = ticket.building_text_raw or (ticket.building.address_text if ticket.building else None)
            if candidate and _normalize_address(candidate) == building_normalized:
                return ticket

    return None


def _set_public_id(ticket: Ticket) -> None:
    if not ticket.public_id:
        ticket.public_id = f"TCK-{ticket.id:04d}"


def _create_inbound_message(
    db: Session,
    payload: WebhookPayload,
    sender_role: str,
    ticket_id: int | None,
    created_at: datetime,
) -> Message:
    message = Message(
        direction=MessageDirection.INBOUND,
        phone_number=payload.phone_number,
        receiving_number=payload.receiving_number,
        sender_role=sender_role,
        raw_text=payload.text,
        image_url=payload.image_url,
        ticket_id=ticket_id,
        created_at=created_at,
    )
    db.add(message)
    db.flush()
    return message


async def process_inbound_whatsapp_message(db: Session, payload: WebhookPayload) -> dict:
    event_time = payload.timestamp or utc_now()

    # Resolve area from receiving number
    area = _resolve_area(db, payload.receiving_number)
    area_buildings = _get_area_buildings(db, area)
    known_buildings = _get_known_buildings_for_llm(area_buildings)

    # Identify sender
    contact = db.query(Contact).filter(Contact.phone_number == payload.phone_number).first()
    sender_role = contact.role.value if contact else "UNKNOWN"

    # Get conversation history for context
    conversation_history = _get_conversation_history(db, payload.phone_number)

    # LLM classification (with conversation context + fuzzy building matching)
    classification: LLMClassification = await classify_message(
        payload.text, known_buildings, conversation_history
    )

    # Resolve building from LLM's building_id (fuzzy match result)
    resolved_building: Building | None = None
    if classification.building_id:
        resolved_building = _find_building_by_id(db, classification.building_id, area)

    # Resolve existing ticket
    ticket: Ticket | None = None
    if classification.ticket_reference:
        ticket = _get_ticket_by_reference(db, classification.ticket_reference, area)

    if ticket is None:
        ticket = _find_recent_open_ticket_for_sender_and_building(
            db,
            payload.phone_number,
            classification.building_reference,
            classification.building_id,
            event_time,
            area,
        )

    action_taken = "updated_ticket" if ticket else "created_ticket"

    if ticket is None:
        # Only map to known buildings. New building records should be created manually, not from WhatsApp text.
        if not resolved_building and classification.building_reference:
            resolved_building = _find_building_by_text(db, classification.building_reference, area)

        supplier = _find_supplier_for_category(db, classification.category, area)

        ticket = Ticket(
            area_id=area.id if area else None,
            building_id=resolved_building.id if resolved_building else None,
            building_text_raw=classification.building_reference or (resolved_building.address_text if resolved_building else None),
            resident_phone=payload.phone_number,
            category=classification.category,
            urgency=classification.urgency.value if classification.urgency else TicketUrgency.MEDIUM.value,
            status=TicketStatus.OPEN,
            assigned_supplier_id=supplier.id if supplier else None,
            description=payload.text,
            created_at=event_time,
            updated_at=event_time,
            sla_due_at=compute_sla_due_at(classification.category, event_time),
        )
        db.add(ticket)
        db.flush()
        _set_public_id(ticket)
    else:
        ticket.updated_at = event_time
        if not ticket.assigned_supplier_id:
            fallback_supplier = _find_supplier_for_category(db, ticket.category, area)
            if fallback_supplier:
                ticket.assigned_supplier_id = fallback_supplier.id

        if classification.is_status_update and classification.new_status:
            ticket.status = classification.new_status
            if classification.new_status == TicketStatus.DONE:
                ticket.completed_at = event_time
        elif sender_role == ContactRole.SUPPLIER.value and classification.new_status:
            ticket.status = classification.new_status
            if classification.new_status == TicketStatus.DONE:
                ticket.completed_at = event_time

    _create_inbound_message(db, payload, sender_role=sender_role, ticket_id=ticket.id, created_at=event_time)

    # Determine from_number for area-specific WhatsApp
    from_number = area.whatsapp_number if area else None

    send_whatsapp_message(
        db,
        phone_number=payload.phone_number,
        text=f"התקבל עדכון לקריאה {ticket.public_id}. סטטוס: {ticket.status.value}.",
        ticket_id=ticket.id,
        from_number=from_number,
    )

    assigned_supplier = ticket.assigned_supplier
    if action_taken == "created_ticket" and assigned_supplier:
        send_whatsapp_message(
            db,
            phone_number=assigned_supplier.phone_number,
            text=(
                f"קריאה חדשה {ticket.public_id}: {ticket.category.value}. "
                f"בניין: {ticket.building_text_raw or 'לא ידוע'}. "
                f"תיאור: {ticket.description}"
            ),
            ticket_id=ticket.id,
            from_number=from_number,
        )

    db.commit()
    db.refresh(ticket)

    return {
        "ticket_public_id": ticket.public_id,
        "public_id": ticket.public_id,         # alias for WebSocket client
        "ticket_id": ticket.id,
        "detected_role": sender_role,
        "detected_building": classification.building_reference,
        "category": ticket.category.value if hasattr(ticket.category, "value") else ticket.category,
        "urgency": ticket.urgency,
        "area_id": area.id if area else None,
        "area_name": area.name if area else None,
        "assigned_supplier": ticket.assigned_supplier.name if ticket.assigned_supplier else None,
        "status": ticket.status.value if hasattr(ticket.status, "value") else ticket.status,
        "sla_due_at": ticket.sla_due_at,
        "action_taken": action_taken,
    }
