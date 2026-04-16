from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.api.tenant import TenantContext, get_building_or_404, get_tenant_context
from app.db import get_db
from app.models import (
    AttendanceRecord,
    Building,
    BuildingWorkerAssignment,
    CleaningWorker,
    User,
    UserRole,
    WorkerDaySwap,
)
from app.schemas import (
    AttendanceRecordOut,
    BuildingLastEntryOut,
    ClockInRequest,
    ClockOutRequest,
)

router = APIRouter(prefix="/attendance", tags=["attendance"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _day_boundaries(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, datetime.min.time())
    return start, start + timedelta(days=1)


def _to_out(rec: AttendanceRecord) -> AttendanceRecordOut:
    duration = None
    if rec.clock_in_at and rec.clock_out_at:
        duration = int((rec.clock_out_at - rec.clock_in_at).total_seconds() / 60)
    return AttendanceRecordOut(
        id=rec.id,
        worker_id=rec.worker_id,
        worker_name=rec.worker.name if rec.worker else "",
        building_id=rec.building_id,
        building_name=rec.building.name if rec.building else "",
        work_date=rec.work_date.date() if isinstance(rec.work_date, datetime) else rec.work_date,
        clock_in_at=rec.clock_in_at,
        clock_out_at=rec.clock_out_at,
        clock_in_lat=rec.clock_in_lat,
        clock_in_lng=rec.clock_in_lng,
        clock_out_lat=rec.clock_out_lat,
        clock_out_lng=rec.clock_out_lng,
        is_swap_day=rec.is_swap_day,
        duration_minutes=duration,
    )


def _worker_for_user(current_user: User, db: Session) -> CleaningWorker:
    if not current_user.worker_id:
        raise HTTPException(status_code=400, detail="User is not linked to a worker profile")
    worker = db.query(CleaningWorker).filter(CleaningWorker.id == current_user.worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker profile not found")
    return worker


def _is_swap_day_for_worker(worker_id: int, building_id: int, d: date, db: Session) -> bool:
    """Returns True if this worker is the *replacement* for this building today."""
    start, end = _day_boundaries(d)
    swap = (
        db.query(WorkerDaySwap)
        .filter(
            WorkerDaySwap.building_id == building_id,
            WorkerDaySwap.replacement_worker_id == worker_id,
            WorkerDaySwap.date >= start,
            WorkerDaySwap.date < end,
        )
        .first()
    )
    return swap is not None


def _allowed_building_ids_for_worker(worker_id: int, d: date, db: Session) -> set[int]:
    start, end = _day_boundaries(d)
    assignments = (
        db.query(BuildingWorkerAssignment.building_id)
        .filter(
            BuildingWorkerAssignment.worker_id == worker_id,
            BuildingWorkerAssignment.is_current == True,
        )
        .all()
    )
    building_ids = {row[0] for row in assignments}

    swaps = (
        db.query(WorkerDaySwap.building_id)
        .filter(
            WorkerDaySwap.replacement_worker_id == worker_id,
            WorkerDaySwap.date >= start,
            WorkerDaySwap.date < end,
        )
        .all()
    )
    building_ids.update(row[0] for row in swaps)
    return building_ids


# ---------------------------------------------------------------------------
# POST /attendance/clock-in
# ---------------------------------------------------------------------------

@router.post("/clock-in", response_model=AttendanceRecordOut, status_code=201)
def clock_in(
    body: ClockInRequest,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AttendanceRecordOut:
    current_user = ctx.user
    worker = _worker_for_user(current_user, db)
    building = get_building_or_404(body.building_id, db, ctx)

    today = date.today()
    start, end = _day_boundaries(today)
    allowed_buildings = _allowed_building_ids_for_worker(worker.id, today, db)
    if body.building_id not in allowed_buildings:
        raise HTTPException(status_code=403, detail="Building not assigned for today")

    # Prevent duplicate clock-in for the same day
    existing = (
        db.query(AttendanceRecord)
        .filter(
            AttendanceRecord.worker_id == worker.id,
            AttendanceRecord.work_date >= start,
            AttendanceRecord.work_date < end,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Already clocked in today. Clock out first before starting a new session.",
        )

    is_swap = _is_swap_day_for_worker(worker.id, body.building_id, today, db)

    rec = AttendanceRecord(
        worker_id=worker.id,
        building_id=body.building_id,
        work_date=start,
        clock_in_at=datetime.utcnow(),
        clock_in_lat=body.latitude,
        clock_in_lng=body.longitude,
        is_swap_day=is_swap,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    # Eager-load relationships for response
    rec = (
        db.query(AttendanceRecord)
        .options(joinedload(AttendanceRecord.worker), joinedload(AttendanceRecord.building))
        .filter(AttendanceRecord.id == rec.id)
        .first()
    )
    return _to_out(rec)


# ---------------------------------------------------------------------------
# POST /attendance/clock-out
# ---------------------------------------------------------------------------

@router.post("/clock-out", response_model=AttendanceRecordOut)
def clock_out(
    body: ClockOutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AttendanceRecordOut:
    worker = _worker_for_user(current_user, db)

    today = date.today()
    start, end = _day_boundaries(today)

    rec = (
        db.query(AttendanceRecord)
        .options(joinedload(AttendanceRecord.worker), joinedload(AttendanceRecord.building))
        .filter(
            AttendanceRecord.worker_id == worker.id,
            AttendanceRecord.work_date >= start,
            AttendanceRecord.work_date < end,
            AttendanceRecord.clock_in_at.isnot(None),
            AttendanceRecord.clock_out_at.is_(None),
        )
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="No active clock-in found for today")

    rec.clock_out_at = datetime.utcnow()
    rec.clock_out_lat = body.latitude
    rec.clock_out_lng = body.longitude
    db.commit()
    db.refresh(rec)
    return _to_out(rec)


# ---------------------------------------------------------------------------
# GET /attendance/me/today  — worker's own status today
# ---------------------------------------------------------------------------

@router.get("/me/today", response_model=AttendanceRecordOut | None)
def my_today(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AttendanceRecordOut | None:
    if not current_user.worker_id:
        return None

    today = date.today()
    start, end = _day_boundaries(today)

    rec = (
        db.query(AttendanceRecord)
        .options(joinedload(AttendanceRecord.worker), joinedload(AttendanceRecord.building))
        .filter(
            AttendanceRecord.worker_id == current_user.worker_id,
            AttendanceRecord.work_date >= start,
            AttendanceRecord.work_date < end,
        )
        .first()
    )
    return _to_out(rec) if rec else None


# ---------------------------------------------------------------------------
# GET /attendance/me/buildings  — buildings worker can clock into today
# ---------------------------------------------------------------------------

@router.get("/me/buildings")
def my_buildings_today(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    if not current_user.worker_id:
        return []

    worker_id = current_user.worker_id
    today = date.today()
    start, end = _day_boundaries(today)

    # Regular assigned buildings
    assignments = (
        db.query(BuildingWorkerAssignment)
        .options(joinedload(BuildingWorkerAssignment.building))
        .filter(
            BuildingWorkerAssignment.worker_id == worker_id,
            BuildingWorkerAssignment.is_current == True,
        )
        .all()
    )
    buildings: dict[int, dict] = {
        a.building_id: {"id": a.building.id, "name": a.building.name, "address": a.building.address_text, "is_swap": False}
        for a in assignments if a.building
    }

    # Swap buildings for today
    swaps = (
        db.query(WorkerDaySwap)
        .options(joinedload(WorkerDaySwap.building))
        .filter(
            WorkerDaySwap.replacement_worker_id == worker_id,
            WorkerDaySwap.date >= start,
            WorkerDaySwap.date < end,
        )
        .all()
    )
    for s in swaps:
        if s.building:
            buildings[s.building_id] = {
                "id": s.building.id,
                "name": s.building.name,
                "address": s.building.address_text,
                "is_swap": True,
            }

    return list(buildings.values())


# ---------------------------------------------------------------------------
# GET /attendance  — area manager / super admin list
# ---------------------------------------------------------------------------

@router.get("", response_model=list[AttendanceRecordOut])
def list_attendance(
    worker_id: int | None = Query(default=None),
    building_id: int | None = Query(default=None),
    from_date: date = Query(default=None, alias="from"),
    to_date: date = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[AttendanceRecordOut]:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if from_date is None:
        from_date = date.today().replace(day=1)
    if to_date is None:
        to_date = date.today()

    start = datetime.combine(from_date, datetime.min.time())
    end = datetime.combine(to_date, datetime.min.time()) + timedelta(days=1)

    query = (
        db.query(AttendanceRecord)
        .options(joinedload(AttendanceRecord.worker), joinedload(AttendanceRecord.building))
        .filter(AttendanceRecord.work_date >= start, AttendanceRecord.work_date < end)
    )
    if not ctx.is_super_admin:
        query = query.join(AttendanceRecord.building).filter(Building.area_id.in_(ctx.area_ids or []))

    if worker_id:
        query = query.filter(AttendanceRecord.worker_id == worker_id)
    if building_id:
        query = query.filter(AttendanceRecord.building_id == building_id)

    records = query.order_by(AttendanceRecord.work_date.desc()).all()
    return [_to_out(r) for r in records]


# ---------------------------------------------------------------------------
# GET /attendance/last-entry  — per building, most recent clock-in
# ---------------------------------------------------------------------------

@router.get("/last-entry", response_model=list[BuildingLastEntryOut])
def last_entry_per_building(
    area_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[BuildingLastEntryOut]:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    effective_area_id = area_id
    if current_user.role == UserRole.AREA_MANAGER:
        effective_area_id = current_user.area_id
    elif area_id is not None and not ctx.is_super_admin and area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    buildings_query = db.query(Building)
    if effective_area_id is not None:
        buildings_query = buildings_query.filter(Building.area_id == effective_area_id)
    elif not ctx.is_super_admin:
        buildings_query = buildings_query.filter(Building.area_id.in_(ctx.area_ids or []))
    buildings = buildings_query.all()

    result = []
    for b in buildings:
        last_rec = (
            db.query(AttendanceRecord)
            .options(joinedload(AttendanceRecord.worker))
            .filter(AttendanceRecord.building_id == b.id)
            .order_by(AttendanceRecord.clock_in_at.desc())
            .first()
        )
        result.append(BuildingLastEntryOut(
            building_id=b.id,
            building_name=b.name,
            address_text=b.address_text,
            last_clock_in_at=last_rec.clock_in_at if last_rec else None,
            last_worker_id=last_rec.worker_id if last_rec else None,
            last_worker_name=last_rec.worker.name if last_rec and last_rec.worker else None,
        ))

    result.sort(key=lambda x: (x.last_clock_in_at is None, x.last_clock_in_at or datetime.min))
    return result
