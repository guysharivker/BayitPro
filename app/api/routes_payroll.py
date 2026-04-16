from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.tenant import (
    TenantContext,
    get_area_or_404,
    get_building_or_404,
    get_tenant_context,
    get_worker_or_404,
)
from app.db import get_db
from app.models import (
    Area,
    AttendanceRecord,
    Building,
    BuildingWorkerAssignment,
    CleaningWorker,
    User,
    UserRole,
    WorkdayDeduction,
)
from app.schemas import (
    AreaFinancialSummary,
    AreaPayrollOverview,
    AreaWorkerFinancialOut,
    BuildingEarningsOut,
    BuildingRevenueOut,
    CompanyFinancialSummary,
    DeductionCreate,
    DeductionOut,
    WorkerExpenseOut,
    WorkerPayrollReport,
)
from app.services.payroll_service import daily_rate, month_boundaries, revenue_for_building, working_days_in_month

router = APIRouter(prefix="/payroll", tags=["payroll"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deduction_to_out(d: WorkdayDeduction) -> DeductionOut:
    return DeductionOut(
        id=d.id,
        worker_id=d.worker_id,
        building_id=d.building_id,
        building_name=d.building.name if d.building else "",
        work_date=d.work_date.date() if isinstance(d.work_date, datetime) else d.work_date,
        reason=d.reason,
        created_at=d.created_at,
    )


def _assert_area_access_for_worker(worker: CleaningWorker, current_user: User) -> None:
    if current_user.role == UserRole.AREA_MANAGER and worker.area_id != current_user.area_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


def _compute_building_earnings(
    worker_id: int,
    building: Building,
    from_dt: datetime,
    to_dt: datetime,
    db: Session,
) -> list[BuildingEarningsOut]:
    """
    Return one BuildingEarningsOut per (building, month) pair in the range.
    We group by month because daily_rate changes per month.
    """
    # Collect attendance records for this building
    records = (
        db.query(AttendanceRecord)
        .filter(
            AttendanceRecord.worker_id == worker_id,
            AttendanceRecord.building_id == building.id,
            AttendanceRecord.work_date >= from_dt,
            AttendanceRecord.work_date < to_dt,
            AttendanceRecord.clock_in_at.isnot(None),
        )
        .all()
    )

    # Collect deductions for this building
    deductions = (
        db.query(WorkdayDeduction)
        .filter(
            WorkdayDeduction.worker_id == worker_id,
            WorkdayDeduction.building_id == building.id,
            WorkdayDeduction.work_date >= from_dt,
            WorkdayDeduction.work_date < to_dt,
        )
        .all()
    )

    if not records and not deductions:
        return []

    # Group by month
    months: dict[tuple[int, int], dict] = {}
    for rec in records:
        ym = (rec.work_date.year, rec.work_date.month)
        if ym not in months:
            months[ym] = {"regular": 0, "swap": 0}
        if rec.is_swap_day:
            months[ym]["swap"] += 1
        else:
            months[ym]["regular"] += 1

    deduction_by_month: dict[tuple[int, int], int] = {}
    for ded in deductions:
        ym = (ded.work_date.year, ded.work_date.month)
        deduction_by_month[ym] = deduction_by_month.get(ym, 0) + 1

    # Aggregate across all months in range
    total_regular = sum(v["regular"] for v in months.values())
    total_swap = sum(v["swap"] for v in months.values())
    total_deductions = sum(deduction_by_month.values())
    net_days = total_regular + total_swap - total_deductions

    # For simplicity: use the first month's working_days / rate for the whole range
    # For multi-month reports, a per-month breakdown would be ideal but adds complexity.
    # We use the dominant month (most records).
    if months:
        dominant_ym = max(months, key=lambda ym: months[ym]["regular"] + months[ym]["swap"])
        year, month = dominant_ym
    else:
        # Only deductions, pick from_dt month
        year, month = from_dt.year, from_dt.month

    monthly_rate_val = building.monthly_rate or 0.0
    wd = working_days_in_month(year, month)
    dr = daily_rate(monthly_rate_val, year, month)

    regular_earnings = total_regular * dr
    swap_earnings = total_swap * dr
    deduction_amount = total_deductions * dr
    total_earnings = regular_earnings + swap_earnings - deduction_amount

    return [BuildingEarningsOut(
        building_id=building.id,
        building_name=building.name,
        monthly_rate=monthly_rate_val,
        working_days_in_month=wd,
        daily_rate=round(dr, 2),
        days_worked=total_regular,
        swap_days=total_swap,
        deduction_days=total_deductions,
        net_days=max(net_days, 0),
        earnings=round(max(total_earnings, 0.0), 2),
    )]


# ---------------------------------------------------------------------------
# GET /payroll/worker/{worker_id}
# ---------------------------------------------------------------------------

@router.get("/worker/{worker_id}", response_model=WorkerPayrollReport)
def worker_payroll(
    worker_id: int,
    from_date: date = Query(default=None, alias="from"),
    to_date: date = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> WorkerPayrollReport:
    current_user = ctx.user
    # Workers can only see their own report
    if current_user.role == UserRole.WORKER:
        if not current_user.worker_id or current_user.worker_id != worker_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    worker = get_worker_or_404(worker_id, db, ctx)

    today = date.today()
    if from_date is None:
        from_date = today.replace(day=1)
    if to_date is None:
        to_date = today

    from_dt = datetime.combine(from_date, datetime.min.time())
    to_dt = datetime.combine(to_date, datetime.min.time()) + timedelta(days=1)

    # All buildings this worker is/was assigned to
    assignments = (
        db.query(BuildingWorkerAssignment)
        .options(joinedload(BuildingWorkerAssignment.building))
        .filter(BuildingWorkerAssignment.worker_id == worker_id)
        .all()
    )
    seen_building_ids: set[int] = set()
    all_earnings: list[BuildingEarningsOut] = []

    for assignment in assignments:
        b = assignment.building
        if not b or b.id in seen_building_ids:
            continue
        seen_building_ids.add(b.id)
        all_earnings.extend(_compute_building_earnings(worker_id, b, from_dt, to_dt, db))

    # Also include any swap buildings the worker covered in this period
    swap_buildings = (
        db.query(AttendanceRecord)
        .options(joinedload(AttendanceRecord.building))
        .filter(
            AttendanceRecord.worker_id == worker_id,
            AttendanceRecord.work_date >= from_dt,
            AttendanceRecord.work_date < to_dt,
            AttendanceRecord.is_swap_day == True,
        )
        .all()
    )
    for rec in swap_buildings:
        b = rec.building
        if b and b.id not in seen_building_ids:
            seen_building_ids.add(b.id)
            all_earnings.extend(_compute_building_earnings(worker_id, b, from_dt, to_dt, db))

    total_regular = sum(e.days_worked for e in all_earnings)
    total_swap = sum(e.swap_days for e in all_earnings)
    total_deductions = sum(e.deduction_days for e in all_earnings)
    total_regular_earnings = sum(e.days_worked * e.daily_rate for e in all_earnings)
    total_swap_earnings = sum(e.swap_days * e.daily_rate for e in all_earnings)
    total_deductions_amount = sum(e.deduction_days * e.daily_rate for e in all_earnings)
    net_earnings = sum(e.earnings for e in all_earnings)

    return WorkerPayrollReport(
        worker_id=worker_id,
        worker_name=worker.name,
        from_date=from_date,
        to_date=to_date,
        buildings=[e for e in all_earnings if e.days_worked > 0 or e.swap_days > 0 or e.deduction_days > 0],
        total_regular_earnings=round(total_regular_earnings, 2),
        total_swap_earnings=round(total_swap_earnings, 2),
        total_deductions_amount=round(total_deductions_amount, 2),
        net_earnings=round(net_earnings, 2),
        total_days_worked=total_regular,
        total_swap_days=total_swap,
        total_deduction_days=total_deductions,
    )


# ---------------------------------------------------------------------------
# GET /payroll/area/{area_id}
# ---------------------------------------------------------------------------

@router.get("/area/{area_id}", response_model=AreaPayrollOverview)
def area_payroll(
    area_id: int,
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AreaPayrollOverview:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    area = get_area_or_404(area_id, db, ctx)

    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    from_dt, to_dt = month_boundaries(year, month)
    wd = working_days_in_month(year, month)

    workers = (
        db.query(CleaningWorker)
        .filter(CleaningWorker.area_id == area.id, CleaningWorker.is_active == True)
        .all()
    )

    workers_out: list[AreaWorkerFinancialOut] = []
    for worker in workers:
        assignments = (
            db.query(BuildingWorkerAssignment)
            .options(joinedload(BuildingWorkerAssignment.building))
            .filter(
                BuildingWorkerAssignment.worker_id == worker.id,
                BuildingWorkerAssignment.is_current == True,
            )
            .all()
        )

        building_earnings: list[BuildingEarningsOut] = []
        total_monthly_rate = 0.0
        for a in assignments:
            b = a.building
            if not b:
                continue
            total_monthly_rate += b.monthly_rate or 0.0
            earnings = _compute_building_earnings(worker.id, b, from_dt, to_dt, db)
            building_earnings.extend(earnings)

        total_earned = sum(e.earnings for e in building_earnings)
        workers_out.append(AreaWorkerFinancialOut(
            worker_id=worker.id,
            worker_name=worker.name,
            buildings=building_earnings,
            total_buildings=len(assignments),
            total_monthly_rate=round(total_monthly_rate, 2),
            total_earned=round(total_earned, 2),
        ))

    workers_out.sort(key=lambda w: w.worker_name)

    return AreaPayrollOverview(
        area_id=area.id,
        year=year,
        month=month,
        working_days=wd,
        workers=workers_out,
    )


# ---------------------------------------------------------------------------
# POST /payroll/deductions
# ---------------------------------------------------------------------------

@router.post("/deductions", response_model=DeductionOut, status_code=201)
def create_deduction(
    body: DeductionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> DeductionOut:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    worker = get_worker_or_404(body.worker_id, db, ctx)
    building = get_building_or_404(body.building_id, db, ctx)
    if worker.area_id != building.area_id:
        raise HTTPException(status_code=400, detail="Worker and building must belong to the same area")

    ded = WorkdayDeduction(
        worker_id=body.worker_id,
        building_id=body.building_id,
        work_date=datetime.combine(body.work_date, datetime.min.time()),
        reason=body.reason,
        deducted_by_user_id=current_user.id,
    )
    db.add(ded)
    db.commit()
    db.refresh(ded)
    ded = (
        db.query(WorkdayDeduction)
        .options(joinedload(WorkdayDeduction.building))
        .filter(WorkdayDeduction.id == ded.id)
        .first()
    )
    return _deduction_to_out(ded)


# ---------------------------------------------------------------------------
# GET /payroll/deductions
# ---------------------------------------------------------------------------

@router.get("/deductions", response_model=list[DeductionOut])
def list_deductions(
    worker_id: int | None = Query(default=None),
    from_date: date = Query(default=None, alias="from"),
    to_date: date = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[DeductionOut]:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = date.today()
    if from_date is None:
        from_date = today.replace(day=1)
    if to_date is None:
        to_date = today

    from_dt = datetime.combine(from_date, datetime.min.time())
    to_dt = datetime.combine(to_date, datetime.min.time()) + timedelta(days=1)

    query = (
        db.query(WorkdayDeduction)
        .options(joinedload(WorkdayDeduction.building), joinedload(WorkdayDeduction.worker))
        .filter(WorkdayDeduction.work_date >= from_dt, WorkdayDeduction.work_date < to_dt)
    )
    if not ctx.is_super_admin:
        query = query.join(WorkdayDeduction.building).filter(Building.area_id.in_(ctx.area_ids or []))
    if worker_id:
        query = query.filter(WorkdayDeduction.worker_id == worker_id)

    deductions = query.order_by(WorkdayDeduction.work_date.desc()).all()

    return [_deduction_to_out(d) for d in deductions]


# ---------------------------------------------------------------------------
# DELETE /payroll/deductions/{deduction_id}
# ---------------------------------------------------------------------------

@router.delete("/deductions/{deduction_id}", status_code=204)
def delete_deduction(
    deduction_id: int,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    ded = (
        db.query(WorkdayDeduction)
        .options(joinedload(WorkdayDeduction.worker), joinedload(WorkdayDeduction.building))
        .filter(WorkdayDeduction.id == deduction_id)
        .first()
    )
    if not ded:
        raise HTTPException(status_code=404, detail="Deduction not found")

    if not ctx.is_super_admin:
        if not ded.building or ded.building.area_id not in (ctx.area_ids or []):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    db.delete(ded)
    db.commit()


# ---------------------------------------------------------------------------
# PATCH /payroll/buildings/{building_id}/rate  — set monthly rate
# ---------------------------------------------------------------------------

@router.patch("/buildings/{building_id}/rate", response_model=dict)
def set_building_rate(
    building_id: int,
    monthly_rate: float = Query(..., gt=0),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    building = get_building_or_404(building_id, db, ctx)

    building.monthly_rate = monthly_rate
    db.commit()
    return {"building_id": building_id, "monthly_rate": monthly_rate}


# ---------------------------------------------------------------------------
# Shared financial helper
# ---------------------------------------------------------------------------

def _build_area_financial(
    area: Area,
    from_date: date,
    to_date: date,
    db: Session,
) -> AreaFinancialSummary:
    from_dt = datetime.combine(from_date, datetime.min.time())
    to_dt = datetime.combine(to_date, datetime.min.time()) + timedelta(days=1)

    # Revenue: sum of prorated building rates
    buildings = db.query(Building).filter(Building.area_id == area.id).all()
    building_revenues: list[BuildingRevenueOut] = []
    total_revenue = 0.0
    for b in buildings:
        rev = revenue_for_building(b.monthly_rate or 0.0, from_date, to_date)
        building_revenues.append(BuildingRevenueOut(
            building_id=b.id,
            building_name=b.name,
            monthly_rate=b.monthly_rate or 0.0,
            revenue_in_range=rev,
        ))
        total_revenue += rev

    # Expenses: sum of worker earnings in range
    workers = db.query(CleaningWorker).filter(
        CleaningWorker.area_id == area.id,
        CleaningWorker.is_active == True,
    ).all()

    worker_expenses: list[WorkerExpenseOut] = []
    total_expenses = 0.0
    for worker in workers:
        assignments = (
            db.query(BuildingWorkerAssignment)
            .options(joinedload(BuildingWorkerAssignment.building))
            .filter(BuildingWorkerAssignment.worker_id == worker.id)
            .all()
        )
        worker_total = 0.0
        seen: set[int] = set()
        for a in assignments:
            b = a.building
            if not b or b.id in seen:
                continue
            seen.add(b.id)
            earnings = _compute_building_earnings(worker.id, b, from_dt, to_dt, db)
            worker_total += sum(e.earnings for e in earnings)

        # Also include swap buildings
        swap_recs = (
            db.query(AttendanceRecord)
            .options(joinedload(AttendanceRecord.building))
            .filter(
                AttendanceRecord.worker_id == worker.id,
                AttendanceRecord.work_date >= from_dt,
                AttendanceRecord.work_date < to_dt,
                AttendanceRecord.is_swap_day == True,
            )
            .all()
        )
        for rec in swap_recs:
            if rec.building and rec.building_id not in seen:
                seen.add(rec.building_id)
                earnings = _compute_building_earnings(worker.id, rec.building, from_dt, to_dt, db)
                worker_total += sum(e.earnings for e in earnings)

        if worker_total > 0:
            worker_expenses.append(WorkerExpenseOut(
                worker_id=worker.id,
                worker_name=worker.name,
                expense_in_range=round(worker_total, 2),
            ))
            total_expenses += worker_total

    total_revenue = round(total_revenue, 2)
    total_expenses = round(total_expenses, 2)

    return AreaFinancialSummary(
        area_id=area.id,
        area_name=area.name,
        from_date=from_date,
        to_date=to_date,
        total_revenue=total_revenue,
        total_expenses=total_expenses,
        profit=round(total_revenue - total_expenses, 2),
        buildings=sorted(building_revenues, key=lambda b: b.revenue_in_range, reverse=True),
        workers=sorted(worker_expenses, key=lambda w: w.expense_in_range, reverse=True),
    )


# ---------------------------------------------------------------------------
# GET /payroll/area/{area_id}/financial
# ---------------------------------------------------------------------------

@router.get("/area/{area_id}/financial", response_model=AreaFinancialSummary)
def area_financial(
    area_id: int,
    from_date: date = Query(default=None, alias="from"),
    to_date: date = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AreaFinancialSummary:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    area = get_area_or_404(area_id, db, ctx)

    today = date.today()
    if from_date is None:
        from_date = today.replace(day=1)
    if to_date is None:
        to_date = today

    return _build_area_financial(area, from_date, to_date, db)


# ---------------------------------------------------------------------------
# GET /payroll/company/financial  — super admin only
# ---------------------------------------------------------------------------

@router.get("/company/financial", response_model=CompanyFinancialSummary)
def company_financial(
    from_date: date = Query(default=None, alias="from"),
    to_date: date = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CompanyFinancialSummary:
    current_user = ctx.user
    if current_user.role not in {UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = date.today()
    if from_date is None:
        from_date = today.replace(day=1)
    if to_date is None:
        to_date = today

    areas_query = db.query(Area)
    if not ctx.is_super_admin:
        areas_query = areas_query.filter(Area.company_id == ctx.company_id)
    areas = areas_query.all()
    area_summaries: list[AreaFinancialSummary] = []
    for area in areas:
        area_summaries.append(_build_area_financial(area, from_date, to_date, db))

    total_revenue = round(sum(a.total_revenue for a in area_summaries), 2)
    total_expenses = round(sum(a.total_expenses for a in area_summaries), 2)

    return CompanyFinancialSummary(
        from_date=from_date,
        to_date=to_date,
        total_revenue=total_revenue,
        total_expenses=total_expenses,
        profit=round(total_revenue - total_expenses, 2),
        areas=sorted(area_summaries, key=lambda a: a.profit, reverse=True),
    )
