"""multi-tenant foundation

Revision ID: 001_multi_tenant_foundation
Revises:
Create Date: 2026-04-16 20:30:00
"""

from collections.abc import Sequence
import re

from alembic import op
import sqlalchemy as sa


revision: str = "001_multi_tenant_foundation"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "company"


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'COMPANY_ADMIN'")

    op.add_column("maintenance_companies", sa.Column("slug", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("company_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("notification_prefs", sa.Text(), nullable=True))
    op.create_index("ix_users_company_id", "users", ["company_id"], unique=False)

    if dialect_name == "postgresql":
        op.create_foreign_key(
            "fk_users_company_id_maintenance_companies",
            "users",
            "maintenance_companies",
            ["company_id"],
            ["id"],
        )

    op.create_table(
        "company_twilio_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("account_sid", sa.String(length=255), nullable=False),
        sa.Column("auth_token_encrypted", sa.Text(), nullable=False),
        sa.Column("default_from_number", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["company_id"], ["maintenance_companies.id"]),
        sa.UniqueConstraint("company_id"),
    )
    op.create_index("ix_company_twilio_credentials_company_id", "company_twilio_credentials", ["company_id"], unique=True)

    companies = bind.execute(sa.text("SELECT id, name FROM maintenance_companies ORDER BY id ASC")).mappings().all()
    seen_slugs: set[str] = set()
    for company in companies:
        slug = _slugify(company["name"] or f"company-{company['id']}")
        unique_slug = slug
        suffix = 2
        while unique_slug in seen_slugs:
            unique_slug = f"{slug}-{suffix}"
            suffix += 1
        seen_slugs.add(unique_slug)
        bind.execute(
            sa.text("UPDATE maintenance_companies SET slug = :slug WHERE id = :company_id"),
            {"slug": unique_slug, "company_id": company["id"]},
        )

    bind.execute(
        sa.text(
            """
            UPDATE users
            SET company_id = (
                SELECT areas.company_id
                FROM areas
                WHERE areas.id = users.area_id
            )
            WHERE users.area_id IS NOT NULL
              AND users.company_id IS NULL
            """
        )
    )

    op.create_index("ix_maintenance_companies_slug", "maintenance_companies", ["slug"], unique=True)

    if dialect_name == "postgresql":
        op.alter_column("maintenance_companies", "slug", nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    op.drop_index("ix_company_twilio_credentials_company_id", table_name="company_twilio_credentials")
    op.drop_table("company_twilio_credentials")

    if dialect_name == "postgresql":
        op.drop_constraint("fk_users_company_id_maintenance_companies", "users", type_="foreignkey")
    op.drop_index("ix_users_company_id", table_name="users")
    op.drop_column("users", "company_id")

    op.drop_index("ix_maintenance_companies_slug", table_name="maintenance_companies")
    op.drop_column("maintenance_companies", "slug")
