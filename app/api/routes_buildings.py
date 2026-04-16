from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.tenant import TenantContext, get_building_or_404, get_tenant_context, get_worker_or_404
from app.db import get_db
from app.models import Building, BuildingWorkerAssignment, CleaningSchedule, CleaningWorker, User, UserRole
from app.schemas import (
    BuildingCreate,
    BuildingOut,
    BuildingUpdate,
    CleaningScheduleCreate,
    CleaningScheduleOut,
    CleaningWorkerOut,
)

router = APIRouter(tags=["buildings"])

_BUILDING_LOAD_OPTIONS = [
    joinedload(Building.cleaning_schedules),
    joinedload(Building.worker_assignments).joinedload(BuildingWorkerAssignment.worker),
]


def _get_current_worker(building: Building) -> CleaningWorkerOut | None:
    for assignment in building.worker_assignments:
        if assignment.is_current:
            return CleaningWorkerOut.model_validate(assignment.worker)
    return None


def _building_to_schema(building: Building) -> BuildingOut:
    data = BuildingOut.model_validate(building, from_attributes=True).model_dump()
    data["current_worker"] = _get_current_worker(building)
    return BuildingOut(**data)


def _worker_building_ids(worker_id: int, db: Session) -> list[int]:
    rows = (
        db.query(BuildingWorkerAssignment.building_id)
        .filter(BuildingWorkerAssignment.worker_id == worker_id, BuildingWorkerAssignment.is_current == True)
        .all()
    )
    return [r[0] for r in rows]


@router.get("/buildings", response_model=list[BuildingOut])
def list_buildings(
    area_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[BuildingOut]:
    current_user = ctx.user
    query = db.query(Building).options(*_BUILDING_LOAD_OPTIONS)

    if current_user.role == UserRole.WORKER:
        building_ids = _worker_building_ids(current_user.worker_id, db)
        if not building_ids:
            return []
        query = query.filter(Building.id.in_(building_ids))
    else:
        if area_id is not None:
            if not ctx.is_super_admin and area_id not in (ctx.area_ids or []):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            query = query.filter(Building.area_id == area_id)
        elif current_user.role == UserRole.AREA_MANAGER:
            query = query.filter(Building.area_id == current_user.area_id)
        elif not ctx.is_super_admin:
            query = query.filter(Building.area_id.in_(ctx.area_ids or []))

    rows = query.order_by(Building.id.asc()).all()
    return [_building_to_schema(row) for row in rows]


@router.get("/buildings/{building_id}", response_model=BuildingOut)
def get_building(
    building_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> BuildingOut:
    current_user = ctx.user
    building = get_building_or_404(building_id, db, ctx)
    building = db.query(Building).options(*_BUILDING_LOAD_OPTIONS).filter(Building.id == building.id).first()

    if current_user.role == UserRole.WORKER:
        allowed = _worker_building_ids(current_user.worker_id, db)
        if building_id not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return _building_to_schema(building)


@router.post("/buildings", response_model=BuildingOut, status_code=201)
def create_building(
    body: BuildingCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> BuildingOut:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if body.area_id is None and not ctx.is_super_admin:
        raise HTTPException(status_code=400, detail="area_id is required")
    if body.area_id is not None and not ctx.is_super_admin and body.area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    building = Building(**body.model_dump())
    db.add(building)
    db.commit()
    db.refresh(building)
    return _building_to_schema(building)


@router.put("/buildings/{building_id}", response_model=BuildingOut)
def update_building(
    building_id: int,
    body: BuildingUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> BuildingOut:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    building = get_building_or_404(building_id, db, ctx)
    building = db.query(Building).options(*_BUILDING_LOAD_OPTIONS).filter(Building.id == building.id).first()

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(building, key, value)

    db.commit()
    db.refresh(building)
    return _building_to_schema(building)


@router.post(
    "/buildings/{building_id}/cleaning-schedules",
    response_model=CleaningScheduleOut,
    status_code=201,
)
def add_cleaning_schedule(
    building_id: int,
    body: CleaningScheduleCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CleaningScheduleOut:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    get_building_or_404(building_id, db, ctx)

    schedule = CleaningSchedule(building_id=building_id, **body.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return CleaningScheduleOut.model_validate(schedule)


@router.delete("/buildings/{building_id}/cleaning-schedules/{schedule_id}", status_code=204)
def delete_cleaning_schedule(
    building_id: int,
    schedule_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    get_building_or_404(building_id, db, ctx)
    schedule = (
        db.query(CleaningSchedule)
        .filter(CleaningSchedule.id == schedule_id, CleaningSchedule.building_id == building_id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Cleaning schedule not found")

    db.delete(schedule)
    db.commit()


@router.post("/buildings/{building_id}/assign-worker", response_model=BuildingOut)
def assign_worker(
    building_id: int,
    worker_id: int = Query(...),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> BuildingOut:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    building = get_building_or_404(building_id, db, ctx)
    building = db.query(Building).options(*_BUILDING_LOAD_OPTIONS).filter(Building.id == building.id).first()
    worker = get_worker_or_404(worker_id, db, ctx)
    if worker.area_id != building.area_id:
        raise HTTPException(status_code=400, detail="Worker must belong to the same area as the building")

    from datetime import datetime
    for assignment in building.worker_assignments:
        if assignment.is_current:
            assignment.is_current = False
            assignment.replaced_at = datetime.utcnow()

    new_assignment = BuildingWorkerAssignment(
        building_id=building_id,
        worker_id=worker_id,
        is_current=True,
    )
    db.add(new_assignment)
    db.commit()
    db.refresh(building)
    return _building_to_schema(building)
