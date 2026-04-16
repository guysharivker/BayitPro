from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    AREA_MANAGER = "AREA_MANAGER"
    WORKER = "WORKER"


class ContactRole(StrEnum):
    RESIDENT = "RESIDENT"
    MANAGER = "MANAGER"
    SUPPLIER = "SUPPLIER"


class TicketCategory(StrEnum):
    CLEANING = "CLEANING"
    ELECTRIC = "ELECTRIC"
    PLUMBING = "PLUMBING"
    ELEVATOR = "ELEVATOR"
    GENERAL = "GENERAL"


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class TicketUrgency(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MessageDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


# --- Workspace hierarchy ---


class MaintenanceCompany(Base):
    __tablename__ = "maintenance_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    areas: Mapped[list["Area"]] = relationship("Area", back_populates="company")
    users: Mapped[list["User"]] = relationship("User", back_populates="company")
    twilio_credential: Mapped["CompanyTwilioCredential | None"] = relationship(
        "CompanyTwilioCredential",
        back_populates="company",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("maintenance_companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    whatsapp_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    company: Mapped[MaintenanceCompany] = relationship("MaintenanceCompany", back_populates="areas")
    manager: Mapped["AreaManager | None"] = relationship("AreaManager", back_populates="area", uselist=False)
    buildings: Mapped[list["Building"]] = relationship("Building", back_populates="area")
    cleaning_workers: Mapped[list["CleaningWorker"]] = relationship("CleaningWorker", back_populates="area")


class AreaManager(Base):
    __tablename__ = "area_managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    area: Mapped[Area] = relationship("Area", back_populates="manager")


class CompanyTwilioCredential(Base):
    __tablename__ = "company_twilio_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("maintenance_companies.id"), unique=True, nullable=False, index=True)
    account_sid: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    default_from_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    company: Mapped[MaintenanceCompany] = relationship("MaintenanceCompany", back_populates="twilio_credential")


# --- Core entities ---


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    role: Mapped[ContactRole] = mapped_column(Enum(ContactRole), nullable=False)


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address_text: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    street_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_floors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_parking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_elevator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entry_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    area: Mapped[Area | None] = relationship("Area", back_populates="buildings")
    cleaning_schedules: Mapped[list["CleaningSchedule"]] = relationship(
        "CleaningSchedule", back_populates="building", cascade="all, delete-orphan"
    )
    worker_assignments: Mapped[list["BuildingWorkerAssignment"]] = relationship(
        "BuildingWorkerAssignment", back_populates="building", cascade="all, delete-orphan"
    )


class CleaningWorker(Base):
    __tablename__ = "cleaning_workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    area: Mapped[Area | None] = relationship("Area", back_populates="cleaning_workers")
    assignments: Mapped[list["BuildingWorkerAssignment"]] = relationship(
        "BuildingWorkerAssignment", back_populates="worker", cascade="all, delete-orphan"
    )


class BuildingWorkerAssignment(Base):
    __tablename__ = "building_worker_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("cleaning_workers.id"), nullable=False, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    building: Mapped["Building"] = relationship("Building", back_populates="worker_assignments")
    worker: Mapped[CleaningWorker] = relationship("CleaningWorker", back_populates="assignments")


class CleaningSchedule(Base):
    __tablename__ = "cleaning_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Sunday .. 6=Saturday
    time: Mapped[str] = mapped_column(String(8), nullable=False)  # "HH:MM"
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    building: Mapped[Building] = relationship("Building", back_populates="cleaning_schedules")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[TicketCategory] = mapped_column(Enum(TicketCategory), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="assigned_supplier")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    public_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True, index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), nullable=True)
    building_text_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resident_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[TicketCategory] = mapped_column(Enum(TicketCategory), nullable=False)
    urgency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus), nullable=False, default=TicketStatus.OPEN)
    assigned_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    building: Mapped[Building | None] = relationship("Building")
    assigned_supplier: Mapped[Supplier | None] = relationship("Supplier", back_populates="tickets")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="ticket")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    receiving_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sender_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    ticket: Mapped[Ticket | None] = relationship("Ticket", back_populates="messages")


class WorkerDaySwap(Base):
    __tablename__ = "worker_day_swaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)  # store as date, query by date
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)
    original_worker_id: Mapped[int] = mapped_column(ForeignKey("cleaning_workers.id"), nullable=False)
    replacement_worker_id: Mapped[int] = mapped_column(ForeignKey("cleaning_workers.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    building: Mapped["Building"] = relationship("Building")
    original_worker: Mapped["CleaningWorker"] = relationship("CleaningWorker", foreign_keys=[original_worker_id])
    replacement_worker: Mapped["CleaningWorker"] = relationship("CleaningWorker", foreign_keys=[replacement_worker_id])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("maintenance_companies.id"), nullable=True, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("cleaning_workers.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    notification_prefs: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string

    company: Mapped["MaintenanceCompany | None"] = relationship("MaintenanceCompany", back_populates="users")
    area: Mapped["Area | None"] = relationship("Area")
    worker: Mapped["CleaningWorker | None"] = relationship("CleaningWorker")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("cleaning_workers.id"), nullable=False, index=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)
    work_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)  # midnight of work day
    clock_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clock_in_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    clock_in_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    clock_out_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    clock_out_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_swap_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # covered another worker's building
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    worker: Mapped["CleaningWorker"] = relationship("CleaningWorker")
    building: Mapped["Building"] = relationship("Building")


class WorkdayDeduction(Base):
    __tablename__ = "workday_deductions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("cleaning_workers.id"), nullable=False, index=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)
    work_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    deducted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    worker: Mapped["CleaningWorker"] = relationship("CleaningWorker")
    building: Mapped["Building"] = relationship("Building")
    deducted_by: Mapped["User | None"] = relationship("User")
