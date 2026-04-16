import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.tenant import (
    TenantContext,
    apply_area_scope,
    ensure_company_access,
    ensure_company_admin_access,
    get_company_or_404,
    get_tenant_context,
)
from app.db import get_db
from app.models import Area, Building, MaintenanceCompany, Ticket, TicketStatus, User, UserRole
from app.schemas import (
    AreaOut,
    AreaSummary,
    CompanyAreaCreate,
    CompanyCreate,
    CompanyDashboard,
    CompanyOut,
    CompanyUserCreate,
    UserOut,
)
from app.services.auth_service import hash_password
from app.services.ticket_service import is_sla_breached

router = APIRouter(tags=["company"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "company"


def _unique_company_slug(raw_slug: str, db: Session) -> str:
    base_slug = _slugify(raw_slug)
    slug = base_slug
    suffix = 2
    while db.query(MaintenanceCompany).filter(MaintenanceCompany.slug == slug).first():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


def _company_to_out(company: MaintenanceCompany, db: Session) -> CompanyOut:
    return CompanyOut(
        id=company.id,
        name=company.name,
        slug=company.slug,
        created_at=company.created_at,
        area_count=db.query(Area).filter(Area.company_id == company.id).count(),
        user_count=db.query(User).filter(User.company_id == company.id).count(),
    )


def _area_to_summary(area: Area, tickets: list[Ticket]) -> AreaSummary:
    open_count = sum(1 for t in tickets if t.status == TicketStatus.OPEN)
    in_progress_count = sum(1 for t in tickets if t.status == TicketStatus.IN_PROGRESS)
    done_count = sum(1 for t in tickets if t.status == TicketStatus.DONE)
    sla_breached = sum(1 for t in tickets if is_sla_breached(t))

    by_category: dict[str, int] = {}
    for ticket in tickets:
        category_key = ticket.category.value
        by_category[category_key] = by_category.get(category_key, 0) + 1

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


def _resolve_dashboard_company_id(
    company_id: int | None,
    db: Session,
    ctx: TenantContext,
) -> int:
    if ctx.user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if ctx.company_id is not None:
        if company_id is not None and company_id != ctx.company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return ctx.company_id

    if company_id is not None:
        return company_id

    company = db.query(MaintenanceCompany).order_by(MaintenanceCompany.id.asc()).first()
    if not company:
        raise HTTPException(status_code=404, detail="No company configured")
    return company.id


@router.get("/company/dashboard", response_model=CompanyDashboard)
def company_dashboard(
    company_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CompanyDashboard:
    selected_company_id = _resolve_dashboard_company_id(company_id, db, ctx)
    company = get_company_or_404(selected_company_id, db)

    areas_query = db.query(Area).options(joinedload(Area.manager)).filter(Area.company_id == company.id)
    areas_query = apply_area_scope(areas_query, Area.id, ctx)
    areas = areas_query.order_by(Area.id.asc()).all()

    area_ids = [area.id for area in areas]
    all_tickets = (
        db.query(Ticket).filter(Ticket.area_id.in_(area_ids)).all()
        if area_ids
        else []
    )
    total_buildings = (
        db.query(Building).filter(Building.area_id.in_(area_ids)).count()
        if area_ids
        else 0
    )

    open_count = sum(1 for ticket in all_tickets if ticket.status == TicketStatus.OPEN)
    in_progress_count = sum(1 for ticket in all_tickets if ticket.status == TicketStatus.IN_PROGRESS)
    done_count = sum(1 for ticket in all_tickets if ticket.status == TicketStatus.DONE)
    sla_breached_count = sum(1 for ticket in all_tickets if is_sla_breached(ticket))

    area_summaries = [
        _area_to_summary(area, [ticket for ticket in all_tickets if ticket.area_id == area.id])
        for area in areas
    ]

    return CompanyDashboard(
        company_name=company.name,
        total_areas=len(areas),
        total_buildings=total_buildings,
        total_tickets=len(all_tickets),
        open_tickets=open_count,
        in_progress_tickets=in_progress_count,
        done_tickets=done_count,
        sla_breached_count=sla_breached_count,
        areas=area_summaries,
    )


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[CompanyOut]:
    if ctx.user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    companies = db.query(MaintenanceCompany).order_by(MaintenanceCompany.id.asc()).all()
    return [_company_to_out(company, db) for company in companies]


@router.post("/companies", response_model=CompanyOut, status_code=201)
def create_company(
    body: CompanyCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CompanyOut:
    if ctx.user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if db.query(User).filter(User.username == body.admin_username).first():
        raise HTTPException(status_code=409, detail="Username already exists")

    company = MaintenanceCompany(
        name=body.name,
        slug=_unique_company_slug(body.slug or body.name, db),
    )
    db.add(company)
    db.flush()

    admin_user = User(
        username=body.admin_username,
        hashed_password=hash_password(body.admin_password),
        full_name=body.admin_full_name,
        role=UserRole.COMPANY_ADMIN,
        company_id=company.id,
        is_active=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(company)
    return _company_to_out(company, db)


@router.post("/companies/{company_id}/areas", response_model=AreaOut, status_code=201)
def create_company_area(
    company_id: int,
    body: CompanyAreaCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AreaOut:
    ensure_company_admin_access(company_id, ctx)
    get_company_or_404(company_id, db)

    existing_number = db.query(Area).filter(Area.whatsapp_number == body.whatsapp_number).first()
    if existing_number:
        raise HTTPException(status_code=409, detail="WhatsApp number already in use")

    area = Area(company_id=company_id, name=body.name, whatsapp_number=body.whatsapp_number)
    db.add(area)
    db.commit()
    db.refresh(area)

    from app.api.routes_areas import _area_to_schema

    return _area_to_schema(area, db)


@router.get("/companies/{company_id}/users", response_model=list[UserOut])
def list_company_users(
    company_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[UserOut]:
    ensure_company_admin_access(company_id, ctx)
    users = (
        db.query(User)
        .filter(User.company_id == company_id)
        .order_by(User.created_at.asc(), User.id.asc())
        .all()
    )
    return [UserOut.model_validate(user) for user in users]


@router.post("/companies/{company_id}/users", response_model=UserOut, status_code=201)
def create_company_user(
    company_id: int,
    body: CompanyUserCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> UserOut:
    ensure_company_admin_access(company_id, ctx)
    get_company_or_404(company_id, db)

    if body.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=400, detail="Use the super admin flow to manage super admins")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")

    area_id = body.area_id
    worker_id = body.worker_id

    if body.role == UserRole.COMPANY_ADMIN:
        area_id = None
        worker_id = None
    elif body.role == UserRole.AREA_MANAGER:
        if area_id is None:
            raise HTTPException(status_code=400, detail="AREA_MANAGER requires area_id")
    elif body.role == UserRole.WORKER:
        if worker_id is None:
            raise HTTPException(status_code=400, detail="WORKER requires worker_id")

    if area_id is not None:
        area = db.query(Area).filter(Area.id == area_id, Area.company_id == company_id).first()
        if not area:
            raise HTTPException(status_code=400, detail="Area does not belong to this company")

    if worker_id is not None:
        from app.models import CleaningWorker

        worker = db.query(CleaningWorker).filter(CleaningWorker.id == worker_id).first()
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        if worker.area_id is None:
            raise HTTPException(status_code=400, detail="Worker is not assigned to an area")
        worker_area = db.query(Area).filter(Area.id == worker.area_id).first()
        if not worker_area or worker_area.company_id != company_id:
            raise HTTPException(status_code=400, detail="Worker does not belong to this company")
        if area_id is None:
            area_id = worker.area_id
        elif area_id != worker.area_id:
            raise HTTPException(status_code=400, detail="worker_id and area_id must point to the same area")

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        company_id=company_id,
        area_id=area_id,
        worker_id=worker_id,
        is_active=body.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
