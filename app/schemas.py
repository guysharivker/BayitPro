from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import MessageDirection, TicketCategory, TicketStatus, UserRole


# --- Webhook ---


class WebhookPayload(BaseModel):
    phone_number: str
    text: str
    image_url: str | None = None
    timestamp: datetime | None = None
    receiving_number: str | None = None


class WebhookResponse(BaseModel):
    ticket_public_id: str
    detected_role: str
    detected_building: str | None
    category: TicketCategory
    urgency: str | None
    area_name: str | None
    assigned_supplier: str | None
    status: TicketStatus
    sla_due_at: datetime | None
    action_taken: str


# --- Messages ---


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    direction: MessageDirection
    phone_number: str
    receiving_number: str | None
    sender_role: str | None
    raw_text: str
    image_url: str | None
    ticket_id: int | None
    created_at: datetime


# --- Suppliers ---


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    area_id: int | None
    name: str
    category: TicketCategory
    phone_number: str


# --- Tickets ---


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str | None
    area_id: int | None
    building_id: int | None = None
    building_name: str | None = None
    building_text_raw: str | None
    resident_phone: str | None
    category: TicketCategory
    urgency: str | None
    status: TicketStatus
    description: str
    created_at: datetime
    updated_at: datetime
    sla_due_at: datetime | None
    completed_at: datetime | None
    sla_breached: bool
    assigned_supplier: SupplierOut | None


class TicketDetailOut(TicketOut):
    messages: list[MessageOut]


# --- Cleaning Schedule ---


class CleaningScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    building_id: int
    day_of_week: int
    time: str
    description: str


class CleaningScheduleCreate(BaseModel):
    day_of_week: int  # 0=Sunday .. 6=Saturday
    time: str  # "HH:MM"
    description: str


# --- Cleaning Workers ---


class CleaningWorkerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    area_id: int | None
    name: str
    phone_number: str
    is_active: bool
    notes: str | None


class WorkerBuildingSummaryOut(BaseModel):
    id: int
    name: str
    address_text: str


class AreaWorkerOut(BaseModel):
    id: int
    area_id: int | None
    name: str
    phone_number: str
    is_active: bool
    notes: str | None
    assigned_building_count: int
    open_ticket_count: int
    critical_ticket_count: int
    assigned_buildings: list[WorkerBuildingSummaryOut]


class BuildingWorkerAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    building_id: int
    worker_id: int
    is_current: bool
    assigned_at: datetime
    replaced_at: datetime | None
    worker: CleaningWorkerOut


# --- Buildings ---


class BuildingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    area_id: int | None
    name: str
    address_text: str
    city: str | None
    street_address: str | None
    latitude: float | None
    longitude: float | None
    num_floors: int | None
    has_parking: bool
    has_elevator: bool
    entry_code: str | None
    notes: str | None
    cleaning_schedules: list[CleaningScheduleOut]
    current_worker: CleaningWorkerOut | None = None


class BuildingCreate(BaseModel):
    area_id: int | None = None
    name: str
    address_text: str
    city: str | None = None
    street_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    num_floors: int | None = None
    has_parking: bool = False
    has_elevator: bool = False
    entry_code: str | None = None
    notes: str | None = None


class BuildingUpdate(BaseModel):
    name: str | None = None
    address_text: str | None = None
    city: str | None = None
    street_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    num_floors: int | None = None
    has_parking: bool | None = None
    has_elevator: bool | None = None
    entry_code: str | None = None
    notes: str | None = None


# --- Area Manager ---


class AreaManagerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone_number: str


# --- Areas ---


class AreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    whatsapp_number: str
    created_at: datetime
    manager: AreaManagerOut | None
    building_count: int
    ticket_count: int


class AreaSummary(BaseModel):
    area_id: int
    area_name: str
    manager_name: str | None
    total_tickets: int
    open_tickets: int
    in_progress_tickets: int
    done_tickets: int
    sla_breached_count: int
    tickets_by_category: dict[str, int]


# --- Area Context (unified at-a-glance summary) ---


class AreaScheduleItemOut(BaseModel):
    worker_id: int
    worker_name: str
    building_id: int
    building_name: str
    schedule_time: str


class AreaAttendanceStatusOut(BaseModel):
    building_id: int
    building_name: str
    clocked_in: bool
    last_worker_name: str | None
    clock_in_at: datetime | None


class AreaContextOut(BaseModel):
    area_id: int
    area_name: str
    open_tickets: int
    sla_breached_count: int
    critical_tickets: int
    todays_schedule: list[AreaScheduleItemOut]
    attendance_status: list[AreaAttendanceStatusOut]


# --- Auth / Profile ---


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    notification_prefs: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: UserRole
    company_id: int | None
    area_id: int | None
    worker_id: int | None
    is_active: bool
    notification_prefs: str | None
    created_at: datetime


# --- Companies ---


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    created_at: datetime
    area_count: int = 0
    user_count: int = 0


class CompanyCreate(BaseModel):
    name: str
    slug: str | None = None
    admin_username: str
    admin_password: str
    admin_full_name: str


class CompanyAreaCreate(BaseModel):
    name: str
    whatsapp_number: str


class CompanyUserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: UserRole
    area_id: int | None = None
    worker_id: int | None = None
    is_active: bool = True


# --- Company Dashboard ---


class CompanyDashboard(BaseModel):
    company_name: str
    total_areas: int
    total_buildings: int
    total_tickets: int
    open_tickets: int
    in_progress_tickets: int
    done_tickets: int
    sla_breached_count: int
    areas: list[AreaSummary]


# --- Alerts ---


class AlertOut(BaseModel):
    alert_type: str  # "sla_warning", "sla_breached", "cleaning_missed"
    severity: str  # "warning", "critical"
    title: str
    description: str
    ticket_id: int | None = None
    building_id: int | None = None
    created_at: datetime


# --- Daily Summary ---


class DailySummaryOut(BaseModel):
    area_id: int | None
    area_name: str | None
    date: str
    summary_text: str
    stats: dict


# --- Schedule & Swaps ---


class SwapCreate(BaseModel):
    date: date
    building_id: int
    replacement_worker_id: int
    reason: str | None = None


class SwapOut(BaseModel):
    id: int
    date: date
    building_id: int
    building_name: str
    original_worker_id: int
    original_worker_name: str
    replacement_worker_id: int
    replacement_worker_name: str
    reason: str | None
    created_at: datetime


class ScheduleBuildingOut(BaseModel):
    building_id: int
    building_name: str
    address_text: str
    schedule_time: str
    open_ticket_count: int
    critical_ticket_count: int
    is_swap: bool


class ScheduleWorkerOut(BaseModel):
    worker_id: int
    worker_name: str
    worker_phone: str
    is_active: bool
    buildings: list[ScheduleBuildingOut]
    total_open_tickets: int
    total_critical_tickets: int


class DailyScheduleOut(BaseModel):
    date: date
    day_of_week: int
    workers: list[ScheduleWorkerOut]
    unassigned_buildings: list[ScheduleBuildingOut]


# --- Attendance ---


class ClockInRequest(BaseModel):
    building_id: int
    latitude: float | None = None
    longitude: float | None = None


class ClockOutRequest(BaseModel):
    latitude: float | None = None
    longitude: float | None = None


class AttendanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    worker_id: int
    worker_name: str
    building_id: int
    building_name: str
    work_date: date
    clock_in_at: datetime | None
    clock_out_at: datetime | None
    clock_in_lat: float | None
    clock_in_lng: float | None
    clock_out_lat: float | None
    clock_out_lng: float | None
    is_swap_day: bool
    duration_minutes: int | None  # computed


class BuildingLastEntryOut(BaseModel):
    building_id: int
    building_name: str
    address_text: str
    last_clock_in_at: datetime | None
    last_worker_id: int | None
    last_worker_name: str | None


# --- Payroll ---


class DeductionCreate(BaseModel):
    worker_id: int
    building_id: int
    work_date: date
    reason: str | None = None


class DeductionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    worker_id: int
    building_id: int
    building_name: str
    work_date: date
    reason: str | None
    created_at: datetime


class BuildingEarningsOut(BaseModel):
    building_id: int
    building_name: str
    monthly_rate: float
    working_days_in_month: int
    daily_rate: float
    days_worked: int
    swap_days: int
    deduction_days: int
    net_days: int
    earnings: float


class WorkerPayrollReport(BaseModel):
    worker_id: int
    worker_name: str
    from_date: date
    to_date: date
    buildings: list[BuildingEarningsOut]
    total_regular_earnings: float
    total_swap_earnings: float
    total_deductions_amount: float
    net_earnings: float
    total_days_worked: int
    total_swap_days: int
    total_deduction_days: int


class AreaWorkerFinancialOut(BaseModel):
    worker_id: int
    worker_name: str
    buildings: list[BuildingEarningsOut]
    total_buildings: int
    total_monthly_rate: float
    total_earned: float


class AreaPayrollOverview(BaseModel):
    area_id: int
    year: int
    month: int
    working_days: int
    workers: list[AreaWorkerFinancialOut]


# --- Financial P&L ---


class BuildingRevenueOut(BaseModel):
    building_id: int
    building_name: str
    monthly_rate: float
    revenue_in_range: float


class WorkerExpenseOut(BaseModel):
    worker_id: int
    worker_name: str
    expense_in_range: float


class AreaFinancialSummary(BaseModel):
    area_id: int
    area_name: str
    from_date: date
    to_date: date
    total_revenue: float
    total_expenses: float
    profit: float
    buildings: list[BuildingRevenueOut]
    workers: list[WorkerExpenseOut]


class CompanyFinancialSummary(BaseModel):
    from_date: date
    to_date: date
    total_revenue: float
    total_expenses: float
    profit: float
    areas: list[AreaFinancialSummary]


# --- Seed ---


class SeedResponse(BaseModel):
    contacts_seeded: int
    suppliers_seeded: int
    buildings_seeded: int
    areas_seeded: int
    area_managers_seeded: int
    cleaning_schedules_seeded: int
    tickets_seeded: int
    users_seeded: int = 0
    swaps_seeded: int = 0
    attendance_seeded: int = 0
    deductions_seeded: int = 0
