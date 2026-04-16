from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.tenant import TenantContext, get_tenant_context
from app.db import get_db
from app.models import Message, Ticket, User, UserRole
from app.schemas import MessageOut

router = APIRouter(tags=["messages"])


@router.get("/messages", response_model=list[MessageOut])
def list_messages(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[MessageOut]:
    current_user = ctx.user
    if current_user.role == UserRole.WORKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    query = db.query(Message).order_by(Message.created_at.desc())
    if not ctx.is_super_admin:
        query = query.join(Message.ticket).filter(Ticket.area_id.in_(ctx.area_ids or []))
    rows = query.limit(limit).all()
    return [MessageOut.model_validate(row) for row in rows]
