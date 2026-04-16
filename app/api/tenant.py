from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import false
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models import Area, Building, CleaningWorker, MaintenanceCompany, User, UserRole


@dataclass
class TenantContext:
    company_id: int | None
    area_ids: list[int] | None
    user: User

    @property
    def is_super_admin(self) -> bool:
        return self.user.role == UserRole.SUPER_ADMIN


def get_tenant_context(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantContext:
    if current_user.role == UserRole.SUPER_ADMIN:
        return TenantContext(company_id=None, area_ids=None, user=current_user)

    company_id = current_user.company_id
    if company_id is None and current_user.area_id is not None:
        area_company = db.query(Area.company_id).filter(Area.id == current_user.area_id).first()
        company_id = area_company[0] if area_company else None

    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to a company",
        )

    if current_user.role in {UserRole.AREA_MANAGER, UserRole.WORKER}:
        if current_user.area_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not assigned to an area",
            )
        area_ids = [current_user.area_id]
    else:
        area_ids = [row[0] for row in db.query(Area.id).filter(Area.company_id == company_id).all()]

    return TenantContext(company_id=company_id, area_ids=area_ids, user=current_user)


def apply_area_scope(query, area_column, ctx: TenantContext):
    if ctx.is_super_admin:
        return query
    if not ctx.area_ids:
        return query.filter(false())
    return query.filter(area_column.in_(ctx.area_ids))


def ensure_company_access(company_id: int, ctx: TenantContext) -> None:
    if ctx.is_super_admin:
        return
    if ctx.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


def ensure_company_admin_access(company_id: int, ctx: TenantContext) -> None:
    if ctx.user.role not in {UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    ensure_company_access(company_id, ctx)


def get_company_or_404(company_id: int, db: Session) -> MaintenanceCompany:
    company = db.query(MaintenanceCompany).filter(MaintenanceCompany.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def get_area_or_404(area_id: int, db: Session, ctx: TenantContext) -> Area:
    area = db.query(Area).filter(Area.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    ensure_company_access(area.company_id, ctx)
    if not ctx.is_super_admin and area.id not in (ctx.area_ids or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return area


def get_building_or_404(building_id: int, db: Session, ctx: TenantContext) -> Building:
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    if building.area_id is None:
        if not ctx.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return building
    if not ctx.is_super_admin and building.area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return building


def get_worker_or_404(worker_id: int, db: Session, ctx: TenantContext) -> CleaningWorker:
    worker = db.query(CleaningWorker).filter(CleaningWorker.id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker.area_id is None:
        if not ctx.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return worker
    if not ctx.is_super_admin and worker.area_id not in (ctx.area_ids or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return worker
