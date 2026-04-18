from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.tenant import TenantContext, get_area_or_404, get_tenant_context
from app.api.routes_buildings import _BUILDING_LOAD_OPTIONS, _building_to_schema
from app.db import get_db
from app.models import (
    Area, AttendanceRecord, Building, BuildingWorkerAssignment,
    CleaningSchedule, CleaningWorker, Ticket, TicketCategory, TicketStatus, User, UserRole,
)
from app.schemas import (
    AreaAttendanceStatusOut, AreaContextOut, AreaOut, AreaScheduleItemOut,
    AreaSummary, AreaWorkerOut, BuildingOut, TicketOut, WorkerBuildingSummaryOut,
)
from app.services.ticket_service import is_sla_breached

router = APIRouter(tags=["areas"])


def _area_to_schema(area: Area, db: Session) -> AreaOut:
    building_count = db.query(Building).filter(Building.area_id == area.id).count()
    ticket_count = db.query(Ticket).filter(Ticket.area_id == area.id).count()

    manager_out = None
    if area.manager:
        from app.schemas import AreaManagerOut
        manager_out = AreaManagerOut.model_validate(area.manager)

    return AreaOut(
        id=area.id,
        company_id=area.company_id,
        name=area.name,
        whatsapp_number=area.whatsapp_number,
        created_at=area.created_at,
        manager=manager_out,
        building_count=building_count,
        ticket_count=ticket_count,
    )


def _build_area_summary(area: Area, db: Session) -> AreaSummary:
    tickets = db.query(Ticket).filter(Ticket.area_id == area.id).all()

    open_count = sum(1 for t in tickets if t.status == TicketStatus.OPEN)
    in_progress_count = sum(1 for t in tickets if t.status == TicketStatus.IN_PROGRESS)
    done_count = sum(1 for t in tickets if t.status == TicketStatus.DONE)
    sla_breached = sum(1 for t in tickets if is_sla_breached(t))

    by_category: dict[str, int] = {}
    for t in tickets:
        cat = t.category.value
        by_category[cat] = by_category.get(cat, 0) + 1

    return AreaSummary(
        area_id=area.id,
        area_name=area.name,
        manager_name=area.manager.name if area.manager else None,
        total_tickets=len(tickets),
        open_tickets=open_count,
        in_progress_tickets=in_progress_count,
        done_tickets=done_count,
        sla_breached_count=sla_breached,
        tickets_by_category=by_category,
    )


def _area_worker_to_schema(worker: CleaningWorker, area_id: int, db: Session) -> AreaWorkerOut:
    assigned_buildings = []
    building_ids: list[int] = []
    for assignment in worker.assignments:
        if not assignment.is_current or not assignment.building or assignment.building.area_id != area_id:
            continue
        assigned_buildings.append(
            WorkerBuildingSummaryOut(
                id=assignment.building.id,
                name=assignment.building.name,
                address_text=assignment.building.address_text,
            )
        )
        building_ids.append(assignment.building.id)

    open_ticket_count = 0
    critical_ticket_count = 0
    if building_ids:
        tickets = (
            db.query(Ticket)
            .filter(Ticket.area_id == area_id, Ticket.building_id.in_(building_ids), Ticket.status != TicketStatus.DONE)
            .all()
        )
        open_ticket_count = len(tickets)
        critical_ticket_count = sum(1 for ticket in tickets if ticket.urgency == "CRITICAL" or is_sla_breached(ticket))

    return AreaWorkerOut(
        id=worker.id,
        area_id=worker.area_id,
        name=worker.name,
        phone_number=worker.phone_number,
        is_active=worker.is_active,
        notes=worker.notes,
        assigned_building_count=len(assigned_buildings),
        open_ticket_count=open_ticket_count,
        critical_ticket_count=critical_ticket_count,
        assigned_buildings=assigned_buildings,
    )


def _check_area_access(area_id: int, ctx: TenantContext, db: Session) -> Area:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return get_area_or_404(area_id, db, ctx)


@router.get("/areas", response_model=list[AreaOut])
def list_areas(
    company_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[AreaOut]:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    query = db.query(Area).options(joinedload(Area.manager))

    if company_id is not None:
        if not ctx.is_super_admin and company_id != ctx.company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        query = query.filter(Area.company_id == company_id)
    elif ctx.company_id is not None:
        query = query.filter(Area.company_id == ctx.company_id)

    if ctx.user.role == UserRole.AREA_MANAGER:
        query = query.filter(Area.id == ctx.user.area_id)

    rows = query.order_by(Area.id.asc()).all()
    return [_area_to_schema(area, db) for area in rows]


@router.get("/areas/{area_id}", response_model=AreaOut)
def get_area(
    area_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AreaOut:
    area = _check_area_access(area_id, ctx, db)
    area = db.query(Area).options(joinedload(Area.manager)).filter(Area.id == area.id).first()
    return _area_to_schema(area, db)


@router.patch("/areas/{area_id}/whatsapp", response_model=AreaOut)
def update_area_whatsapp(
    area_id: int,
    whatsapp_number: str,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AreaOut:
    """Update the WhatsApp number for an area (superadmin / company admin only)."""
    if ctx.user.role not in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    area = _check_area_access(area_id, ctx, db)
    # Normalize: strip whatsapp: prefix, keep +digits
    cleaned = whatsapp_number.strip()
    if cleaned.startswith("whatsapp:"):
        cleaned = cleaned.split("whatsapp:", maxsplit=1)[1]
    area.whatsapp_number = cleaned
    db.commit()
    db.refresh(area)
    return _area_to_schema(area, db)


@router.get("/areas/{area_id}/buildings", response_model=list[BuildingOut])
def list_area_buildings(
    area_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[BuildingOut]:
    _check_area_access(area_id, ctx, db)

    query = db.query(Building).options(*_BUILDING_LOAD_OPTIONS).filter(Building.area_id == area_id)

    buildings = query.order_by(Building.id.asc()).all()
    return [_building_to_schema(building) for building in buildings]


@router.get("/areas/{area_id}/tickets", response_model=list[TicketOut])
def list_area_tickets(
    area_id: int,
    status: TicketStatus | None = Query(default=None),
    category: TicketCategory | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[TicketOut]:
    _check_area_access(area_id, ctx, db)

    query = db.query(Ticket).options(joinedload(Ticket.assigned_supplier), joinedload(Ticket.building)).filter(Ticket.area_id == area_id)

    if status:
        query = query.filter(Ticket.status == status)
    if category:
        query = query.filter(Ticket.category == category)

    rows = query.order_by(Ticket.created_at.desc()).all()

    from app.api.routes_tickets import _ticket_to_schema
    return [_ticket_to_schema(ticket) for ticket in rows]


@router.get("/areas/{area_id}/summary", response_model=AreaSummary)
def get_area_summary(
    area_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AreaSummary:
    _check_area_access(area_id, ctx, db)
    area = db.query(Area).options(joinedload(Area.manager)).filter(Area.id == area_id).first()
    return _build_area_summary(area, db)


@router.get("/areas/{area_id}/workers", response_model=list[AreaWorkerOut])
def list_area_workers(
    area_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[AreaWorkerOut]:
    _check_area_access(area_id, ctx, db)

    workers = (
        db.query(CleaningWorker)
        .options(joinedload(CleaningWorker.assignments).joinedload(BuildingWorkerAssignment.building))
        .filter(
            or_(
                CleaningWorker.area_id == area_id,
                CleaningWorker.assignments.any(
                    BuildingWorkerAssignment.building.has(Building.area_id == area_id)
                ),
            )
        )
        .order_by(CleaningWorker.is_active.desc(), CleaningWorker.name.asc())
        .all()
    )

    return [_area_worker_to_schema(worker, area_id, db) for worker in workers]


@router.get("/areas/{area_id}/context", response_model=AreaContextOut)
def get_area_context(
    area_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AreaContextOut:
    """Unified at-a-glance context for an area: ticket KPIs, today's schedule, attendance status."""
    area = _check_area_access(area_id, ctx, db)
    area = db.query(Area).options(joinedload(Area.manager)).filter(Area.id == area.id).first()

    # --- Ticket KPIs ---
    tickets = db.query(Ticket).filter(Ticket.area_id == area_id, Ticket.status != TicketStatus.DONE).all()
    open_count = sum(1 for t in tickets if t.status == TicketStatus.OPEN)
    sla_breached = sum(1 for t in tickets if is_sla_breached(t))
    critical = sum(1 for t in tickets if t.urgency == "CRITICAL" or is_sla_breached(t))

    # --- Today's schedule ---
    today = date.today()
    db_dow = (today.weekday() + 1) % 7  # Mon=1 … Sun=0
    schedules = (
        db.query(CleaningSchedule)
        .options(joinedload(CleaningSchedule.building))
        .join(CleaningSchedule.building)
        .filter(Building.area_id == area_id, CleaningSchedule.day_of_week == db_dow)
        .all()
    )
    schedule_items: list[AreaScheduleItemOut] = []
    for sched in schedules:
        building = sched.building
        assignment = (
            db.query(BuildingWorkerAssignment)
            .options(joinedload(BuildingWorkerAssignment.worker))
            .filter(BuildingWorkerAssignment.building_id == building.id, BuildingWorkerAssignment.is_current == True)
            .first()
        )
        if assignment and assignment.worker:
            schedule_items.append(AreaScheduleItemOut(
                worker_id=assignment.worker.id,
                worker_name=assignment.worker.name,
                building_id=building.id,
                building_name=building.name,
                schedule_time=sched.time,
            ))

    # --- Attendance status for today ---
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    buildings = db.query(Building).filter(Building.area_id == area_id).all()
    attendance_status: list[AreaAttendanceStatusOut] = []
    for building in buildings:
        rec = (
            db.query(AttendanceRecord)
            .options(joinedload(AttendanceRecord.worker))
            .filter(
                AttendanceRecord.building_id == building.id,
                AttendanceRecord.work_date >= day_start,
                AttendanceRecord.work_date < day_end,
            )
            .order_by(AttendanceRecord.clock_in_at.desc().nulls_last())
            .first()
        )
        attendance_status.append(AreaAttendanceStatusOut(
            building_id=building.id,
            building_name=building.name,
            clocked_in=rec is not None and rec.clock_in_at is not None and rec.clock_out_at is None,
            last_worker_name=rec.worker.name if rec and rec.worker else None,
            clock_in_at=rec.clock_in_at if rec else None,
        ))

    return AreaContextOut(
        area_id=area_id,
        area_name=area.name,
        open_tickets=open_count,
        sla_breached_count=sla_breached,
        critical_tickets=critical,
        todays_schedule=schedule_items,
        attendance_status=attendance_status,
    )
