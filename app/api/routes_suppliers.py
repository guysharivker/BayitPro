from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.tenant import TenantContext, get_tenant_context
from app.db import get_db
from app.models import Supplier, User, UserRole
from app.schemas import SupplierOut
from fastapi import HTTPException, status

router = APIRouter(tags=["suppliers"])


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[SupplierOut]:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    query = db.query(Supplier)
    if not ctx.is_super_admin:
        query = query.filter(or_(Supplier.area_id.is_(None), Supplier.area_id.in_(ctx.area_ids or [])))
    rows = query.order_by(Supplier.id.asc()).all()
    return [SupplierOut.model_validate(row) for row in rows]
