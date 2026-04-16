import pathlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_areas import router as areas_router
from app.api.routes_attendance import router as attendance_router
from app.api.routes_auth import router as auth_router
from app.api.routes_buildings import router as buildings_router
from app.api.routes_company import router as company_router
from app.api.routes_messages import router as messages_router
from app.api.routes_payroll import router as payroll_router
from app.api.routes_schedule import router as schedule_router
from app.api.routes_suppliers import router as suppliers_router
from app.api.routes_tickets import router as tickets_router
from app.api.routes_webhook import router as webhook_router
from app.config import ALLOWED_ORIGINS
from app.db import Base, SessionLocal, engine
from app.models import User, UserRole
from app.services.auth_service import hash_password
from app.services.notifier import connected_clients

Base.metadata.create_all(bind=engine)

# Create default super-admin if no users exist
def _ensure_default_admin() -> None:
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(User(
                username="admin",
                hashed_password=hash_password("admin123"),
                full_name="מנהל ראשי",
                role=UserRole.SUPER_ADMIN,
                company_id=None,
            ))
            db.commit()
    finally:
        db.close()

_ensure_default_admin()

STATIC_DIR = pathlib.Path(__file__).parent / "static"

app = FastAPI(title="Building Maintenance WhatsApp MVP", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_router)
app.include_router(attendance_router)
app.include_router(payroll_router)
app.include_router(schedule_router)
app.include_router(webhook_router)
app.include_router(tickets_router)
app.include_router(messages_router)
app.include_router(suppliers_router)
app.include_router(buildings_router)
app.include_router(areas_router)
app.include_router(company_router)


@app.get("/")
def dashboard_page():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/login")
def login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))


@app.get("/health")
def health() -> dict[str, str]:
    try:
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok" if db_status == "ok" else "degraded", "db": db_status, "service": "bayitpro"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(websocket)
