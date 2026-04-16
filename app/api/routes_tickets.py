import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.api.tenant import TenantContext, apply_area_scope, get_building_or_404, get_tenant_context
from app.db import get_db
from app.models import Building, BuildingWorkerAssignment, Ticket, TicketCategory, TicketStatus, User, UserRole
from app.schemas import MessageOut, SupplierOut, TicketDetailOut, TicketOut
from app.services.ticket_service import is_sla_breached

router = APIRouter(tags=["tickets"])


def _ticket_to_schema(ticket: Ticket) -> TicketOut:
    supplier_schema = SupplierOut.model_validate(ticket.assigned_supplier) if ticket.assigned_supplier else None
    building_name = None
    if ticket.building:
        building_name = ticket.building.name
    elif ticket.building_text_raw:
        building_name = ticket.building_text_raw
    return TicketOut(
        id=ticket.id,
        public_id=ticket.public_id,
        area_id=ticket.area_id,
        building_id=ticket.building_id,
        building_name=building_name,
        building_text_raw=ticket.building_text_raw,
        resident_phone=ticket.resident_phone,
        category=ticket.category,
        urgency=ticket.urgency,
        status=ticket.status,
        description=ticket.description,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        sla_due_at=ticket.sla_due_at,
        completed_at=ticket.completed_at,
        sla_breached=is_sla_breached(ticket),
        assigned_supplier=supplier_schema,
    )


def _worker_building_ids(worker_id: int, db: Session) -> list[int]:
    rows = (
        db.query(BuildingWorkerAssignment.building_id)
        .filter(BuildingWorkerAssignment.worker_id == worker_id, BuildingWorkerAssignment.is_current == True)
        .all()
    )
    return [r[0] for r in rows]


@router.get("/tickets", response_model=list[TicketOut])
def list_tickets(
    area_id: int | None = Query(default=None),
    status: TicketStatus | None = Query(default=None),
    category: TicketCategory | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[TicketOut]:
    current_user = ctx.user
    query = db.query(Ticket).options(joinedload(Ticket.assigned_supplier), joinedload(Ticket.building))

    if current_user.role == UserRole.AREA_MANAGER:
        query = query.filter(Ticket.area_id == current_user.area_id)
    elif current_user.role == UserRole.WORKER:
        building_ids = _worker_building_ids(current_user.worker_id, db)
        if not building_ids:
            return []
        query = query.filter(Ticket.building_id.in_(building_ids))
    else:
        if area_id is not None:
            if not ctx.is_super_admin and area_id not in (ctx.area_ids or []):
                raise HTTPException(status_code=403, detail="Access denied")
            query = query.filter(Ticket.area_id == area_id)
        query = apply_area_scope(query, Ticket.area_id, ctx)

    if status is not None:
        query = query.filter(Ticket.status == status)
    if category is not None:
        query = query.filter(Ticket.category == category)

    rows = query.order_by(Ticket.created_at.desc()).all()
    return [_ticket_to_schema(row) for row in rows]


@router.get("/tickets/{ticket_id}", response_model=TicketDetailOut)
def get_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> TicketDetailOut:
    current_user = ctx.user
    query = db.query(Ticket).options(joinedload(Ticket.assigned_supplier), joinedload(Ticket.messages))

    if ticket_id.upper().startswith("TCK-"):
        ticket = query.filter(Ticket.public_id == ticket_id.upper()).first()
    elif ticket_id.isdigit():
        ticket = query.filter(Ticket.id == int(ticket_id)).first()
    else:
        raise HTTPException(status_code=400, detail="ticket_id must be numeric or TCK-XXXX")

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Scope check
    if not ctx.is_super_admin and ticket.area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=403, detail="Access denied")
    if current_user.role == UserRole.AREA_MANAGER and ticket.area_id != current_user.area_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if current_user.role == UserRole.WORKER:
        building_ids = _worker_building_ids(current_user.worker_id, db)
        if ticket.building_id not in building_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    base = _ticket_to_schema(ticket)
    messages = [MessageOut.model_validate(msg) for msg in sorted(ticket.messages, key=lambda m: m.created_at)]
    return TicketDetailOut(**base.model_dump(), messages=messages)


class WorkerTicketCreate(BaseModel):
    building_id: int
    category: TicketCategory
    description: str
    urgency: str | None = "MEDIUM"


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket_by_worker(
    body: WorkerTicketCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> TicketOut:
    """Workers (and managers/admins) can open a ticket directly from the UI."""
    current_user = ctx.user
    # Workers may only report on their own assigned buildings
    if current_user.role == UserRole.WORKER:
        allowed = _worker_building_ids(current_user.worker_id, db)
        if body.building_id not in allowed:
            raise HTTPException(status_code=403, detail="Building not assigned to this worker")

    building = get_building_or_404(body.building_id, db, ctx)

    ticket = Ticket(
        public_id=f"TCK-{uuid.uuid4().hex[:6].upper()}",
        area_id=building.area_id,
        building_id=building.id,
        building_text_raw=building.name,
        category=body.category,
        urgency=body.urgency,
        status=TicketStatus.OPEN,
        description=body.description,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _ticket_to_schema(ticket)


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


@router.patch("/tickets/{ticket_id}/status", response_model=TicketOut)
def update_ticket_status(
    ticket_id: int,
    body: TicketStatusUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> TicketOut:
    current_user = ctx.user
    ticket = db.query(Ticket).options(joinedload(Ticket.assigned_supplier), joinedload(Ticket.building)).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not ctx.is_super_admin and ticket.area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=403, detail="Access denied")
    if current_user.role == UserRole.AREA_MANAGER and ticket.area_id != current_user.area_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if current_user.role == UserRole.WORKER:
        building_ids = _worker_building_ids(current_user.worker_id, db)
        if ticket.building_id not in building_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    ticket.status = body.status
    ticket.updated_at = datetime.utcnow()
    if body.status == TicketStatus.DONE:
        ticket.completed_at = datetime.utcnow()
    elif ticket.completed_at and body.status != TicketStatus.DONE:
        ticket.completed_at = None
    db.commit()
    db.refresh(ticket)
    return _ticket_to_schema(ticket)
