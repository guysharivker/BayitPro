from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.api.tenant import TenantContext, get_building_or_404, get_tenant_context, get_worker_or_404
from app.db import get_db
from app.models import (
    Building,
    BuildingWorkerAssignment,
    CleaningSchedule,
    CleaningWorker,
    Ticket,
    TicketStatus,
    User,
    UserRole,
    WorkerDaySwap,
)
from app.schemas import DailyScheduleOut, ScheduleBuildingOut, ScheduleWorkerOut, SwapCreate, SwapOut
from app.services.ticket_service import is_sla_breached

router = APIRouter(prefix="/schedule", tags=["schedule"])

# day_of_week in DB: 0=Sunday … 6=Saturday
# Python's weekday(): 0=Monday … 6=Sunday  →  need conversion
_PYTHON_TO_DB = {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7 % 7, 6: 0}  # Mon→2 … Sun→0


def _python_dow_to_db(d: date) -> int:
    """Convert a Python date to the 0=Sunday…6=Saturday convention used in CleaningSchedule."""
    return (d.weekday() + 1) % 7  # Mon=1,Tue=2,…,Sat=6,Sun=0


def _open_tickets_for_building(building_id: int, db: Session) -> list[Ticket]:
    return (
        db.query(Ticket)
        .filter(Ticket.building_id == building_id, Ticket.status != TicketStatus.DONE)
        .all()
    )


def _current_worker_for_building(building_id: int, db: Session) -> CleaningWorker | None:
    assignment = (
        db.query(BuildingWorkerAssignment)
        .options(joinedload(BuildingWorkerAssignment.worker))
        .filter(BuildingWorkerAssignment.building_id == building_id, BuildingWorkerAssignment.is_current == True)
        .first()
    )
    return assignment.worker if assignment else None


def _schedule_building(
    building: Building,
    schedule_time: str,
    tickets: list[Ticket],
    is_swap: bool,
) -> ScheduleBuildingOut:
    open_count = len(tickets)
    critical_count = sum(1 for t in tickets if t.urgency == "CRITICAL" or is_sla_breached(t))
    return ScheduleBuildingOut(
        building_id=building.id,
        building_name=building.name,
        address_text=building.address_text,
        schedule_time=schedule_time,
        open_ticket_count=open_count,
        critical_ticket_count=critical_count,
        is_swap=is_swap,
    )


def _check_area_access_for_building(building: Building, current_user: User) -> None:
    if current_user.role == UserRole.AREA_MANAGER and building.area_id != current_user.area_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


# ---------------------------------------------------------------------------
# GET /schedule/daily
# ---------------------------------------------------------------------------

@router.get("/daily", response_model=DailyScheduleOut)
def daily_schedule(
    target_date: date = Query(default=None, alias="date"),
    area_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> DailyScheduleOut:
    current_user = ctx.user
    if target_date is None:
        target_date = date.today()

    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    effective_area_id = area_id
    if current_user.role == UserRole.AREA_MANAGER:
        effective_area_id = current_user.area_id
    elif area_id is not None and not ctx.is_super_admin and area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    dow = _python_dow_to_db(target_date)

    # All cleaning schedules for this day
    schedule_query = (
        db.query(CleaningSchedule)
        .options(joinedload(CleaningSchedule.building))
        .join(CleaningSchedule.building)
        .filter(CleaningSchedule.day_of_week == dow)
    )
    if effective_area_id is not None:
        schedule_query = schedule_query.filter(Building.area_id == effective_area_id)
    elif not ctx.is_super_admin:
        schedule_query = schedule_query.filter(Building.area_id.in_(ctx.area_ids or []))
    schedules = schedule_query.all()

    if not schedules:
        return DailyScheduleOut(date=target_date, day_of_week=dow, workers=[], unassigned_buildings=[])

    # Load all swaps for this date
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    swaps = (
        db.query(WorkerDaySwap)
        .filter(WorkerDaySwap.date >= day_start, WorkerDaySwap.date < day_end)
        .all()
    )
    swap_map: dict[int, WorkerDaySwap] = {s.building_id: s for s in swaps}

    # Build worker → buildings map
    worker_buildings: dict[int, tuple[CleaningWorker, list[tuple[ScheduleBuildingOut]]]] = {}
    unassigned: list[ScheduleBuildingOut] = []

    for cs in schedules:
        building = cs.building
        tickets = _open_tickets_for_building(building.id, db)
        has_swap = building.id in swap_map

        if has_swap:
            swap = swap_map[building.id]
            worker = db.query(CleaningWorker).filter(CleaningWorker.id == swap.replacement_worker_id).first()
        else:
            worker = _current_worker_for_building(building.id, db)

        sb = _schedule_building(building, cs.time, tickets, is_swap=has_swap)

        if worker is None:
            unassigned.append(sb)
        else:
            if worker.id not in worker_buildings:
                worker_buildings[worker.id] = (worker, [])
            worker_buildings[worker.id][1].append(sb)

    # Build response
    workers_out = []
    for worker, buildings in worker_buildings.values():
        total_open = sum(b.open_ticket_count for b in buildings)
        total_critical = sum(b.critical_ticket_count for b in buildings)
        workers_out.append(ScheduleWorkerOut(
            worker_id=worker.id,
            worker_name=worker.name,
            worker_phone=worker.phone_number,
            is_active=worker.is_active,
            buildings=sorted(buildings, key=lambda b: b.schedule_time),
            total_open_tickets=total_open,
            total_critical_tickets=total_critical,
        ))

    workers_out.sort(key=lambda w: (-w.total_critical_tickets, -w.total_open_tickets, w.worker_name))

    return DailyScheduleOut(
        date=target_date,
        day_of_week=dow,
        workers=workers_out,
        unassigned_buildings=unassigned,
    )


# ---------------------------------------------------------------------------
# GET /schedule/my-week — worker's own buildings for the next 7 days
# ---------------------------------------------------------------------------

@router.get("/my-week")
def my_weekly_schedule(
    from_date: date = Query(default=None, alias="from"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    if not current_user.worker_id:
        raise HTTPException(status_code=400, detail="User is not linked to a worker profile")

    if from_date is None:
        from_date = date.today()

    worker_id = current_user.worker_id
    result = []

    for i in range(7):
        day = from_date + timedelta(days=i)
        dow = _python_dow_to_db(day)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        # Regular assigned buildings scheduled on this day of week
        schedules = (
            db.query(CleaningSchedule)
            .join(BuildingWorkerAssignment,
                  BuildingWorkerAssignment.building_id == CleaningSchedule.building_id)
            .options(joinedload(CleaningSchedule.building))
            .filter(
                CleaningSchedule.day_of_week == dow,
                BuildingWorkerAssignment.worker_id == worker_id,
                BuildingWorkerAssignment.is_current == True,
            )
            .all()
        )

        buildings = []
        seen_building_ids: set[int] = set()
        for cs in schedules:
            if cs.building and cs.building_id not in seen_building_ids:
                seen_building_ids.add(cs.building_id)
                tickets = _open_tickets_for_building(cs.building_id, db)
                open_count = len(tickets)
                critical_count = sum(1 for t in tickets if t.urgency == "CRITICAL" or is_sla_breached(t))
                buildings.append({
                    "building_id": cs.building_id,
                    "building_name": cs.building.name,
                    "address_text": cs.building.address_text,
                    "schedule_time": cs.time,
                    "is_swap": False,
                    "open_ticket_count": open_count,
                    "critical_ticket_count": critical_count,
                })

        # Swap buildings where this worker is the replacement for this day
        swaps = (
            db.query(WorkerDaySwap)
            .options(joinedload(WorkerDaySwap.building))
            .filter(
                WorkerDaySwap.replacement_worker_id == worker_id,
                WorkerDaySwap.date >= day_start,
                WorkerDaySwap.date < day_end,
            )
            .all()
        )
        for swap in swaps:
            if swap.building and swap.building_id not in seen_building_ids:
                seen_building_ids.add(swap.building_id)
                cs = (
                    db.query(CleaningSchedule)
                    .filter(
                        CleaningSchedule.building_id == swap.building_id,
                        CleaningSchedule.day_of_week == dow,
                    )
                    .first()
                )
                tickets = _open_tickets_for_building(swap.building_id, db)
                open_count = len(tickets)
                critical_count = sum(1 for t in tickets if t.urgency == "CRITICAL" or is_sla_breached(t))
                buildings.append({
                    "building_id": swap.building_id,
                    "building_name": swap.building.name,
                    "address_text": swap.building.address_text,
                    "schedule_time": cs.time if cs else "",
                    "is_swap": True,
                    "open_ticket_count": open_count,
                    "critical_ticket_count": critical_count,
                })

        result.append({
            "date": day.isoformat(),
            "day_of_week": dow,
            "buildings": sorted(buildings, key=lambda b: b["schedule_time"]),
        })

    return result


# ---------------------------------------------------------------------------
# POST /schedule/swaps
# ---------------------------------------------------------------------------

@router.post("/swaps", response_model=SwapOut, status_code=201)
def create_swap(
    body: SwapCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> SwapOut:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    building = get_building_or_404(body.building_id, db, ctx)
    replacement = get_worker_or_404(body.replacement_worker_id, db, ctx)
    if replacement.area_id != building.area_id:
        raise HTTPException(status_code=400, detail="Replacement worker must belong to the same area")

    original_worker = _current_worker_for_building(body.building_id, db)
    if not original_worker:
        raise HTTPException(status_code=400, detail="No current worker assigned to this building")

    # Check no duplicate swap for same building+date
    day_start = datetime.combine(body.date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    existing = (
        db.query(WorkerDaySwap)
        .filter(
            WorkerDaySwap.building_id == body.building_id,
            WorkerDaySwap.date >= day_start,
            WorkerDaySwap.date < day_end,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Swap already exists for this building on this date")

    swap = WorkerDaySwap(
        date=day_start,
        building_id=body.building_id,
        original_worker_id=original_worker.id,
        replacement_worker_id=body.replacement_worker_id,
        reason=body.reason,
    )
    db.add(swap)
    db.commit()
    db.refresh(swap)

    return _swap_to_out(swap)


# ---------------------------------------------------------------------------
# GET /schedule/swaps
# ---------------------------------------------------------------------------

@router.get("/swaps", response_model=list[SwapOut])
def list_swaps(
    from_date: date = Query(default=None, alias="from"),
    to_date: date = Query(default=None, alias="to"),
    area_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[SwapOut]:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if from_date is None:
        from_date = date.today()
    if to_date is None:
        to_date = from_date + timedelta(days=30)

    query = (
        db.query(WorkerDaySwap)
        .options(
            joinedload(WorkerDaySwap.building),
            joinedload(WorkerDaySwap.original_worker),
            joinedload(WorkerDaySwap.replacement_worker),
        )
        .filter(
            WorkerDaySwap.date >= datetime.combine(from_date, datetime.min.time()),
            WorkerDaySwap.date < datetime.combine(to_date + timedelta(days=1), datetime.min.time()),
        )
        .order_by(WorkerDaySwap.date.asc())
    )

    swaps = query.all()

    effective_area_id = area_id
    if current_user.role == UserRole.AREA_MANAGER:
        effective_area_id = current_user.area_id
    elif area_id is not None and not ctx.is_super_admin and area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if effective_area_id is not None:
        swaps = [s for s in swaps if s.building and s.building.area_id == effective_area_id]
    elif not ctx.is_super_admin:
        swaps = [s for s in swaps if s.building and s.building.area_id in (ctx.area_ids or [])]

    return [_swap_to_out(s) for s in swaps]


# ---------------------------------------------------------------------------
# DELETE /schedule/swaps/{swap_id}
# ---------------------------------------------------------------------------

@router.delete("/swaps/{swap_id}", status_code=204)
def delete_swap(
    swap_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    swap = (
        db.query(WorkerDaySwap)
        .options(joinedload(WorkerDaySwap.building))
        .filter(WorkerDaySwap.id == swap_id)
        .first()
    )
    if not swap:
        raise HTTPException(status_code=404, detail="Swap not found")

    if not ctx.is_super_admin:
        if not swap.building or swap.building.area_id not in (ctx.area_ids or []):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    db.delete(swap)
    db.commit()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _swap_to_out(swap: WorkerDaySwap) -> SwapOut:
    return SwapOut(
        id=swap.id,
        date=swap.date.date() if isinstance(swap.date, datetime) else swap.date,
        building_id=swap.building_id,
        building_name=swap.building.name if swap.building else "",
        original_worker_id=swap.original_worker_id,
        original_worker_name=swap.original_worker.name if swap.original_worker else "",
        replacement_worker_id=swap.replacement_worker_id,
        replacement_worker_name=swap.replacement_worker.name if swap.replacement_worker else "",
        reason=swap.reason,
        created_at=swap.created_at,
    )
