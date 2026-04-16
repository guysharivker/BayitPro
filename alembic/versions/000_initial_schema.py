"""initial schema

Revision ID: 000_initial_schema
Revises:
Create Date: 2026-04-17

Creates the full base schema (all tables as they existed before multi-tenant additions).
Migration 001 then adds multi-tenant columns on top.

For existing SQLite dev databases: do NOT run this migration.
Run: alembic stamp 000_initial_schema && alembic upgrade head
     (or just: alembic stamp head  if already at 001)
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "000_initial_schema"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # Enum types — on SQLite these are stored as VARCHAR; on PostgreSQL they are
    # real TYPE objects created automatically by SQLAlchemy during create_table.
    # We declare them here for use in column definitions below.
    userrole_type = sa.Enum("SUPER_ADMIN", "AREA_MANAGER", "WORKER", name="userrole")
    contactrole_type = sa.Enum("RESIDENT", "MANAGER", "SUPPLIER", name="contactrole")
    ticketcategory_type = sa.Enum("CLEANING", "ELECTRIC", "PLUMBING", "ELEVATOR", "GENERAL", name="ticketcategory")
    ticketstatus_type = sa.Enum("OPEN", "IN_PROGRESS", "DONE", name="ticketstatus")
    messagedirection_type = sa.Enum("INBOUND", "OUTBOUND", name="messagedirection")

    bool_false = sa.text("false") if is_pg else sa.text("0")
    bool_true = sa.text("true") if is_pg else sa.text("1")

    # ── maintenance_companies ─────────────────────────────────────────────────
    # NOTE: no "slug" column here — that is added by migration 001.
    op.create_table(
        "maintenance_companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_maintenance_companies_id", "maintenance_companies", ["id"], unique=False)

    # ── areas ─────────────────────────────────────────────────────────────────
    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("maintenance_companies.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("whatsapp_number", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_areas_id", "areas", ["id"], unique=False)
    op.create_index("ix_areas_whatsapp_number", "areas", ["whatsapp_number"], unique=True)

    # ── area_managers ─────────────────────────────────────────────────────────
    op.create_table(
        "area_managers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("area_id"),
    )
    op.create_index("ix_area_managers_id", "area_managers", ["id"], unique=False)
    op.create_index("ix_area_managers_phone_number", "area_managers", ["phone_number"], unique=True)

    # ── contacts ──────────────────────────────────────────────────────────────
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("role", contactrole_type, nullable=False),
    )
    op.create_index("ix_contacts_id", "contacts", ["id"], unique=False)
    op.create_index("ix_contacts_phone_number", "contacts", ["phone_number"], unique=True)

    # ── buildings ─────────────────────────────────────────────────────────────
    op.create_table(
        "buildings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address_text", sa.String(255), nullable=False),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("street_address", sa.String(255), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("num_floors", sa.Integer(), nullable=True),
        sa.Column("has_parking", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("has_elevator", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("entry_code", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("monthly_rate", sa.Float(), nullable=True),
    )
    op.create_index("ix_buildings_id", "buildings", ["id"], unique=False)
    op.create_index("ix_buildings_area_id", "buildings", ["area_id"], unique=False)
    op.create_index("ix_buildings_address_text", "buildings", ["address_text"], unique=True)

    # ── cleaning_workers ──────────────────────────────────────────────────────
    op.create_table(
        "cleaning_workers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_cleaning_workers_id", "cleaning_workers", ["id"], unique=False)
    op.create_index("ix_cleaning_workers_area_id", "cleaning_workers", ["area_id"], unique=False)
    op.create_index("ix_cleaning_workers_phone_number", "cleaning_workers", ["phone_number"], unique=True)

    # ── building_worker_assignments ───────────────────────────────────────────
    op.create_table(
        "building_worker_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("building_id", sa.Integer(), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("cleaning_workers.id"), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("assigned_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("replaced_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_building_worker_assignments_id", "building_worker_assignments", ["id"], unique=False)
    op.create_index("ix_building_worker_assignments_building_id", "building_worker_assignments", ["building_id"], unique=False)
    op.create_index("ix_building_worker_assignments_worker_id", "building_worker_assignments", ["worker_id"], unique=False)

    # ── cleaning_schedules ────────────────────────────────────────────────────
    op.create_table(
        "cleaning_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("building_id", sa.Integer(), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("time", sa.String(8), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
    )
    op.create_index("ix_cleaning_schedules_id", "cleaning_schedules", ["id"], unique=False)
    op.create_index("ix_cleaning_schedules_building_id", "cleaning_schedules", ["building_id"], unique=False)

    # ── suppliers ─────────────────────────────────────────────────────────────
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", ticketcategory_type, nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False),
    )
    op.create_index("ix_suppliers_id", "suppliers", ["id"], unique=False)
    op.create_index("ix_suppliers_area_id", "suppliers", ["area_id"], unique=False)
    op.create_index("ix_suppliers_category", "suppliers", ["category"], unique=False)
    op.create_index("ix_suppliers_phone_number", "suppliers", ["phone_number"], unique=True)

    # ── tickets ───────────────────────────────────────────────────────────────
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(32), nullable=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("building_id", sa.Integer(), sa.ForeignKey("buildings.id"), nullable=True),
        sa.Column("building_text_raw", sa.String(255), nullable=True),
        sa.Column("resident_phone", sa.String(32), nullable=True),
        sa.Column("category", ticketcategory_type, nullable=False),
        sa.Column("urgency", sa.String(32), nullable=True),
        sa.Column("status", ticketstatus_type, nullable=False, server_default="OPEN"),
        sa.Column("assigned_supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("sla_due_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tickets_id", "tickets", ["id"], unique=False)
    op.create_index("ix_tickets_area_id", "tickets", ["area_id"], unique=False)
    op.create_index("ix_tickets_public_id", "tickets", ["public_id"], unique=True)

    # ── messages ──────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("direction", messagedirection_type, nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("receiving_number", sa.String(32), nullable=True),
        sa.Column("sender_role", sa.String(32), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(1024), nullable=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_messages_id", "messages", ["id"], unique=False)
    op.create_index("ix_messages_direction", "messages", ["direction"], unique=False)
    op.create_index("ix_messages_phone_number", "messages", ["phone_number"], unique=False)
    op.create_index("ix_messages_ticket_id", "messages", ["ticket_id"], unique=False)

    # ── worker_day_swaps ──────────────────────────────────────────────────────
    op.create_table(
        "worker_day_swaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("building_id", sa.Integer(), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("original_worker_id", sa.Integer(), sa.ForeignKey("cleaning_workers.id"), nullable=False),
        sa.Column("replacement_worker_id", sa.Integer(), sa.ForeignKey("cleaning_workers.id"), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_worker_day_swaps_id", "worker_day_swaps", ["id"], unique=False)
    op.create_index("ix_worker_day_swaps_date", "worker_day_swaps", ["date"], unique=False)
    op.create_index("ix_worker_day_swaps_building_id", "worker_day_swaps", ["building_id"], unique=False)

    # ── users ─────────────────────────────────────────────────────────────────
    # NOTE: no "company_id" or "notification_prefs" here — added by migration 001.
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", userrole_type, nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("cleaning_workers.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # ── attendance_records ────────────────────────────────────────────────────
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("cleaning_workers.id"), nullable=False),
        sa.Column("building_id", sa.Integer(), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("work_date", sa.DateTime(), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(), nullable=True),
        sa.Column("clock_out_at", sa.DateTime(), nullable=True),
        sa.Column("clock_in_lat", sa.Float(), nullable=True),
        sa.Column("clock_in_lng", sa.Float(), nullable=True),
        sa.Column("clock_out_lat", sa.Float(), nullable=True),
        sa.Column("clock_out_lng", sa.Float(), nullable=True),
        sa.Column("is_swap_day", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_attendance_records_id", "attendance_records", ["id"], unique=False)
    op.create_index("ix_attendance_records_worker_id", "attendance_records", ["worker_id"], unique=False)
    op.create_index("ix_attendance_records_building_id", "attendance_records", ["building_id"], unique=False)
    op.create_index("ix_attendance_records_work_date", "attendance_records", ["work_date"], unique=False)

    # ── workday_deductions ────────────────────────────────────────────────────
    op.create_table(
        "workday_deductions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("cleaning_workers.id"), nullable=False),
        sa.Column("building_id", sa.Integer(), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("work_date", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("deducted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_workday_deductions_id", "workday_deductions", ["id"], unique=False)
    op.create_index("ix_workday_deductions_worker_id", "workday_deductions", ["worker_id"], unique=False)
    op.create_index("ix_workday_deductions_building_id", "workday_deductions", ["building_id"], unique=False)
    op.create_index("ix_workday_deductions_work_date", "workday_deductions", ["work_date"], unique=False)


def downgrade() -> None:
    op.drop_table("workday_deductions")
    op.drop_table("attendance_records")
    op.drop_table("users")
    op.drop_table("worker_day_swaps")
    op.drop_table("messages")
    op.drop_table("tickets")
    op.drop_table("suppliers")
    op.drop_table("cleaning_schedules")
    op.drop_table("building_worker_assignments")
    op.drop_table("cleaning_workers")
    op.drop_table("buildings")
    op.drop_table("contacts")
    op.drop_table("area_managers")
    op.drop_table("areas")
    op.drop_table("maintenance_companies")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS messagedirection")
        op.execute("DROP TYPE IF EXISTS ticketstatus")
        op.execute("DROP TYPE IF EXISTS ticketcategory")
        op.execute("DROP TYPE IF EXISTS contactrole")
        op.execute("DROP TYPE IF EXISTS userrole")
