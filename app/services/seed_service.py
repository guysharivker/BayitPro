"""Seed service — generates a realistic demo dataset for BayitPro.

Produces:
- 1 company
- 5 areas (central Tel Aviv / Ramat Gan / Givatayim) + managers
- 250 buildings (50 per area) with monthly rates (₪2,500–₪5,500)
- 25 cleaning workers (5 per area) with building assignments
- Cleaning schedules per building (2–5 days/week)
- ~140 tickets covering March 1 – April 11, 2026
- 5 global suppliers
- User accounts: admin + 5 area managers (demo123) + 25 workers (worker123)
- Worker day swaps: 2 per area in March
- Attendance records: March 1 – April 7, 2026 (~92% attendance rate)
- Workday deductions: 2 per area

The seed is idempotent — re-running /seed without reset only fills missing data.
For a clean rebuild: POST /seed?reset=true
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    Area,
    AreaManager,
    AttendanceRecord,
    Building,
    BuildingWorkerAssignment,
    CleaningSchedule,
    CleaningWorker,
    Contact,
    ContactRole,
    MaintenanceCompany,
    Supplier,
    Ticket,
    TicketCategory,
    TicketStatus,
    TicketUrgency,
    User,
    UserRole,
    WorkdayDeduction,
    WorkerDaySwap,
)
from app.services.auth_service import hash_password
from app.services.payroll_service import is_working_day
from app.services.ticket_service import compute_sla_due_at


def _slugify_company_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "company"


# =============================================================================
# Area / street configuration
# =============================================================================

AREAS_CONFIG: list[dict] = [
    {
        "name": "תל אביב - לב העיר",
        "whatsapp_number": "+14155551001",
        "city": "תל אביב",
        "manager": {"name": "שירלי גולן", "phone": "+972501000001"},
        "username": "tlaviv1",
        "streets": [
            ("רוטשילד", 32.0645, 34.7730, 12),
            ("אלנבי", 32.0700, 34.7705, 12),
            ("שינקין", 32.0728, 34.7735, 10),
            ("המלך ג'ורג'", 32.0743, 34.7745, 10),
            ("נחלת בנימין", 32.0680, 34.7690, 6),
        ],
    },
    {
        "name": "תל אביב - מרכז ים",
        "whatsapp_number": "+14155551002",
        "city": "תל אביב",
        "manager": {"name": "אבי דהן", "phone": "+972501000002"},
        "username": "tlaviv2",
        "streets": [
            ("דיזנגוף", 32.0810, 34.7745, 12),
            ("בן יהודה", 32.0830, 34.7705, 12),
            ("הירקון", 32.0845, 34.7685, 10),
            ("גורדון", 32.0821, 34.7700, 10),
            ("פרישמן", 32.0806, 34.7720, 6),
        ],
    },
    {
        "name": "תל אביב - צפון הישן",
        "whatsapp_number": "+14155551003",
        "city": "תל אביב",
        "manager": {"name": "יעל מזרחי", "phone": "+972501000003"},
        "username": "tlaviv3",
        "streets": [
            ("אבן גבירול", 32.0880, 34.7838, 12),
            ("ויצמן", 32.0905, 34.7870, 12),
            ("פנקס", 32.0925, 34.7880, 10),
            ("אנטוקולסקי", 32.0890, 34.7860, 8),
            ("ז'בוטינסקי", 32.0870, 34.7855, 8),
        ],
    },
    {
        "name": "רמת גן מרכז",
        "whatsapp_number": "+14155551004",
        "city": "רמת גן",
        "manager": {"name": "דנה ברוך", "phone": "+972501000004"},
        "username": "ramatgan",
        "streets": [
            ("ביאליק", 32.0825, 34.8135, 12),
            ("ז'בוטינסקי", 32.0840, 34.8100, 12),
            ("אבא הלל סילבר", 32.0870, 34.8125, 10),
            ("הרא\"ה", 32.0855, 34.8155, 10),
            ("ארלוזורוב", 32.0812, 34.8160, 6),
        ],
    },
    {
        "name": "גבעתיים",
        "whatsapp_number": "+14155551005",
        "city": "גבעתיים",
        "manager": {"name": "רונן פרץ", "phone": "+972501000005"},
        "username": "givataim",
        "streets": [
            ("ויצמן", 32.0720, 34.8090, 12),
            ("כצנלסון", 32.0740, 34.8115, 12),
            ("סירקין", 32.0715, 34.8135, 10),
            ("ארלוזורוב", 32.0705, 34.8070, 10),
            ("כורזין", 32.0750, 34.8105, 6),
        ],
    },
]

WORKER_NAMES: list[list[str]] = [
    ["אחמד חאלד", "ולדימיר סלבצ'וק", "מוחמד ג'בר", "סרגיי פטרוב", "מרים אסולין"],
    ["יוסף עמר", "נטליה איבנוב", "איברהים נסראללה", "אולג גרין", "פאטמה זועבי"],
    ["אנטון קוזלוב", "ג'מאל דיאב", "לודמילה פבלוב", "עלי חסן", "תמיר אוחיון"],
    ["רמזי אבו עיד", "מיכאיל שברוב", "חוסאם ג'בארין", "דמיטרי ולקוב", "אלכסנדרה רז"],
    ["וואליד סלימאן", "בוריס קצנלסון", "סאלח אלקאסם", "פיוטר נובק", "סבטלנה ברון"],
]

GLOBAL_SUPPLIERS = [
    {"name": "CleanCo", "category": TicketCategory.CLEANING, "phone_number": "+972503000101"},
    {"name": "ElectroFix", "category": TicketCategory.ELECTRIC, "phone_number": "+972503000102"},
    {"name": "PipePros", "category": TicketCategory.PLUMBING, "phone_number": "+972503000103"},
    {"name": "LiftLine", "category": TicketCategory.ELEVATOR, "phone_number": "+972503000104"},
    {"name": "GeneralCare", "category": TicketCategory.GENERAL, "phone_number": "+972503000105"},
]

TICKET_TEMPLATES: list[dict] = [
    {"category": TicketCategory.PLUMBING, "urgency": TicketUrgency.CRITICAL, "text": "נזילה חזקה בחדר מדרגות קומה {floor}, המים זורמים למטה!"},
    {"category": TicketCategory.PLUMBING, "urgency": TicketUrgency.HIGH, "text": "סתימה בביוב הראשי, ריח נוראי בכל הבניין"},
    {"category": TicketCategory.PLUMBING, "urgency": TicketUrgency.HIGH, "text": "אין מים חמים בכל הקומה כבר מהבוקר"},
    {"category": TicketCategory.PLUMBING, "urgency": TicketUrgency.MEDIUM, "text": "ברז טפטוף בחדר האשפה, מים מצטברים על הרצפה"},
    {"category": TicketCategory.PLUMBING, "urgency": TicketUrgency.MEDIUM, "text": "הצינור בחדר מדרגות רטוב, נראה שמתחיל לטפטף"},
    {"category": TicketCategory.PLUMBING, "urgency": TicketUrgency.LOW, "text": "לחץ המים נמוך בקומה {floor}"},
    {"category": TicketCategory.ELECTRIC, "urgency": TicketUrgency.CRITICAL, "text": "הפסקת חשמל מלאה בכל הבניין, המעלית לא עובדת"},
    {"category": TicketCategory.ELECTRIC, "urgency": TicketUrgency.HIGH, "text": "קצר חשמלי בלוח החשמל של הקומה, ניצוצות!"},
    {"category": TicketCategory.ELECTRIC, "urgency": TicketUrgency.HIGH, "text": "התאורה בחדר מדרגות לא עובדת כבר יומיים, חושך מוחלט"},
    {"category": TicketCategory.ELECTRIC, "urgency": TicketUrgency.MEDIUM, "text": "נורה שרופה בלובי, צריך החלפה"},
    {"category": TicketCategory.ELECTRIC, "urgency": TicketUrgency.MEDIUM, "text": "השלט של שער החניון לא מגיב"},
    {"category": TicketCategory.ELECTRIC, "urgency": TicketUrgency.LOW, "text": "נורות בחדר מדרגות מהבהבות"},
    {"category": TicketCategory.ELEVATOR, "urgency": TicketUrgency.CRITICAL, "text": "המעלית תקועה בקומה {floor}, יש אנשים בפנים!"},
    {"category": TicketCategory.ELEVATOR, "urgency": TicketUrgency.HIGH, "text": "המעלית עושה רעשים חזקים ומתנדנדת, מפחיד לעלות"},
    {"category": TicketCategory.ELEVATOR, "urgency": TicketUrgency.HIGH, "text": "המעלית לא עובדת כבר מהבוקר, קשישים לא יכולים לצאת"},
    {"category": TicketCategory.ELEVATOR, "urgency": TicketUrgency.MEDIUM, "text": "הדלת של המעלית נסגרת לאט מאוד"},
    {"category": TicketCategory.ELEVATOR, "urgency": TicketUrgency.LOW, "text": "הנורה במעלית לא עובדת"},
    {"category": TicketCategory.CLEANING, "urgency": TicketUrgency.HIGH, "text": "יש ג'וקים בחדר אשפה ובחדר מדרגות, צריך הדברה דחוף"},
    {"category": TicketCategory.CLEANING, "urgency": TicketUrgency.MEDIUM, "text": "הלובי מאוד מלוכלך, לא נוקה כבר שבוע"},
    {"category": TicketCategory.CLEANING, "urgency": TicketUrgency.MEDIUM, "text": "פח האשפה עולה על גדותיו, צריך פינוי"},
    {"category": TicketCategory.CLEANING, "urgency": TicketUrgency.MEDIUM, "text": "הלובי מלוכלך אחרי שיפוץ בדירה, אבק וסיד בכל מקום"},
    {"category": TicketCategory.CLEANING, "urgency": TicketUrgency.LOW, "text": "צריך לנקות את חדר האשפה, ריח לא נעים"},
    {"category": TicketCategory.CLEANING, "urgency": TicketUrgency.LOW, "text": "העובד לא הגיע הבוקר לניקיון הלובי"},
    {"category": TicketCategory.GENERAL, "urgency": TicketUrgency.HIGH, "text": "הדלת הראשית לא נסגרת, כל אחד יכול להיכנס לבניין"},
    {"category": TicketCategory.GENERAL, "urgency": TicketUrgency.MEDIUM, "text": "האינטרקום לא עובד לדירה {floor}"},
    {"category": TicketCategory.GENERAL, "urgency": TicketUrgency.MEDIUM, "text": "שער החניון לא נפתח עם הסנסור"},
    {"category": TicketCategory.GENERAL, "urgency": TicketUrgency.LOW, "text": "תיבת דואר שבורה בכניסה לבניין"},
    {"category": TicketCategory.GENERAL, "urgency": TicketUrgency.LOW, "text": "שלט הבניין דהה וצריך החלפה"},
]


# =============================================================================
# Helpers
# =============================================================================

def _det_rand(seed: str) -> random.Random:
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    return random.Random(h)


def _jitter_coord(base_lat: float, base_lng: float, seed: str) -> tuple[float, float]:
    rng = _det_rand(seed)
    return (
        round(base_lat + (rng.random() - 0.5) * 0.004, 6),
        round(base_lng + (rng.random() - 0.5) * 0.004, 6),
    )


def _building_profile(rng: random.Random) -> dict:
    num_floors = rng.randint(4, 15)
    units = rng.choice([8, 12, 16, 20, 24, 32, 40, 48])
    notes_templates = [
        f"בניין מגורים, {units} דירות, {num_floors} קומות",
        f"בניין מגורים משופץ, {units} דירות",
        f"מגדל מגורים, {units} דירות, {num_floors} קומות",
        f"בניין ישן, {units} דירות, דרוש תחזוקה שוטפת",
        f"בניין משופץ לאחרונה, {units} דירות",
        f"בניין מגורים + משרדים, {units} יחידות",
    ]
    # Monthly rate by building size
    if num_floors <= 6:
        rate = rng.choice([2500, 2500, 3000, 3000, 3500])
    elif num_floors <= 10:
        rate = rng.choice([3500, 4000, 4000, 4500])
    else:
        rate = rng.choice([4500, 5000, 5000, 5500])

    return {
        "num_floors": num_floors,
        "has_elevator": num_floors > 4 or rng.random() < 0.25,
        "has_parking": rng.random() < 0.72,
        "entry_code": str(rng.randint(1000, 9999)),
        "notes": rng.choice(notes_templates),
        "monthly_rate": float(rate),
    }


def _cleaning_schedule_for_building(rng: random.Random, building_id: int) -> list[dict]:
    num_sessions = rng.choice([2, 2, 3, 3, 3, 5])
    possible_days = [0, 1, 2, 3, 4, 5]  # Sun-Fri (DB convention 0=Sun)
    days = sorted(rng.sample(possible_days, min(num_sessions, len(possible_days))))
    time = rng.choice(["06:30", "07:00", "07:30", "08:00", "08:30"])
    descriptions = [
        "ניקיון חדר מדרגות וכניסה",
        "ניקיון לובי ומעליות",
        "ניקיון כללי + חניון",
        "ניקיון חדרי מדרגות",
        "שטיפת לובי ומעלית",
        "ניקיון יסודי שבועי",
    ]
    return [
        {"building_id": building_id, "day_of_week": d, "time": time, "description": rng.choice(descriptions)}
        for d in days
    ]


def _resident_for(area_idx: int, resident_idx: int) -> dict:
    phone = f"+97250200{area_idx + 1:01d}{resident_idx + 1:03d}"
    names = [
        ["דנה כהן", "יוסי לוי", "מיכל אברהם", "אורי דוד", "רונית שמעון"],
        ["תמר פרץ", "עופר בן דוד", "שירה חדד", "גיא אזולאי", "נועה כרמי"],
        ["רן חיים", "ליאת שטרן", "אסף ברק", "קרן טל", "עידו רפאלי"],
        ["מאיה זיו", "יובל גל", "רותם שמש", "הדר פוגל", "אלון מרקוס"],
        ["שרון לב", "דור יצחקי", "מיטל ששון", "ארז רוזן", "ענת ברנע"],
    ]
    return {"name": names[area_idx][resident_idx], "phone": phone}


# =============================================================================
# Working days for the demo period
# =============================================================================

DEMO_START = date(2026, 3, 1)
DEMO_END = date(2026, 4, 7)   # last working day before today (April 11 Sat)


def _demo_working_days() -> list[date]:
    """All working days from DEMO_START to DEMO_END inclusive."""
    result = []
    current = DEMO_START
    while current <= DEMO_END:
        if is_working_day(current):
            result.append(current)
        current += timedelta(days=1)
    return result


# =============================================================================
# Main seed function
# =============================================================================

def seed_data(db: Session) -> dict:
    counts = {
        "contacts_seeded": 0,
        "suppliers_seeded": 0,
        "buildings_seeded": 0,
        "areas_seeded": 0,
        "area_managers_seeded": 0,
        "cleaning_schedules_seeded": 0,
        "tickets_seeded": 0,
        "users_seeded": 0,
        "swaps_seeded": 0,
        "attendance_seeded": 0,
        "deductions_seeded": 0,
    }

    # -------------------------------------------------------------------------
    # Company
    # -------------------------------------------------------------------------
    company = db.query(MaintenanceCompany).first()
    if not company:
        company = MaintenanceCompany(
            name="BayitPro אחזקה",
            slug=_slugify_company_name("BayitPro אחזקה"),
        )
        db.add(company)
        db.flush()

    # -------------------------------------------------------------------------
    # Areas + Area Managers + Contacts
    # -------------------------------------------------------------------------
    area_objects: list[Area] = []
    for area_cfg in AREAS_CONFIG:
        area = db.query(Area).filter(Area.whatsapp_number == area_cfg["whatsapp_number"]).first()
        if not area:
            area = Area(company_id=company.id, name=area_cfg["name"], whatsapp_number=area_cfg["whatsapp_number"])
            db.add(area)
            db.flush()
            counts["areas_seeded"] += 1

        if not db.query(AreaManager).filter(AreaManager.area_id == area.id).first():
            db.add(AreaManager(area_id=area.id, name=area_cfg["manager"]["name"], phone_number=area_cfg["manager"]["phone"]))
            counts["area_managers_seeded"] += 1

        for area_cfg2 in AREAS_CONFIG:
            mgr = area_cfg2["manager"]
            if not db.query(Contact).filter(Contact.phone_number == mgr["phone"]).first():
                db.add(Contact(name=mgr["name"], phone_number=mgr["phone"], role=ContactRole.MANAGER))
                counts["contacts_seeded"] += 1

        for i in range(5):
            r = _resident_for(AREAS_CONFIG.index(area_cfg), i)
            if not db.query(Contact).filter(Contact.phone_number == r["phone"]).first():
                db.add(Contact(name=r["name"], phone_number=r["phone"], role=ContactRole.RESIDENT))
                counts["contacts_seeded"] += 1

        area_objects.append(area)

    db.flush()

    # -------------------------------------------------------------------------
    # Global suppliers
    # -------------------------------------------------------------------------
    supplier_by_category: dict[TicketCategory, Supplier] = {}
    for sup_cfg in GLOBAL_SUPPLIERS:
        existing = db.query(Supplier).filter(Supplier.phone_number == sup_cfg["phone_number"]).first()
        if existing:
            supplier_by_category[sup_cfg["category"]] = existing
        else:
            s = Supplier(name=sup_cfg["name"], category=sup_cfg["category"], phone_number=sup_cfg["phone_number"], area_id=None)
            db.add(s)
            db.flush()
            supplier_by_category[sup_cfg["category"]] = s
            counts["suppliers_seeded"] += 1
            if not db.query(Contact).filter(Contact.phone_number == sup_cfg["phone_number"]).first():
                db.add(Contact(name=sup_cfg["name"], phone_number=sup_cfg["phone_number"], role=ContactRole.SUPPLIER))
                counts["contacts_seeded"] += 1

    db.flush()

    # -------------------------------------------------------------------------
    # Buildings (50 per area, with monthly_rate)
    # -------------------------------------------------------------------------
    all_buildings_by_area: dict[int, list[Building]] = {}

    for area, area_cfg in zip(area_objects, AREAS_CONFIG):
        area_buildings: list[Building] = []
        for street_name, base_lat, base_lng, building_count in area_cfg["streets"]:
            for bnum in range(1, building_count + 1):
                address_text = f"רחוב {street_name} {bnum} {area_cfg['city']}"
                existing = db.query(Building).filter(Building.address_text == address_text).first()
                if existing:
                    # Backfill monthly_rate if missing
                    if existing.monthly_rate is None:
                        rng = _det_rand(address_text)
                        profile = _building_profile(rng)
                        existing.monthly_rate = profile["monthly_rate"]
                    area_buildings.append(existing)
                    continue

                lat, lng = _jitter_coord(base_lat, base_lng, address_text)
                rng = _det_rand(address_text)
                profile = _building_profile(rng)
                building = Building(
                    area_id=area.id,
                    name=f"{street_name} {bnum}",
                    address_text=address_text,
                    city=area_cfg["city"],
                    street_address=f"{street_name} {bnum}",
                    latitude=lat,
                    longitude=lng,
                    num_floors=profile["num_floors"],
                    has_parking=profile["has_parking"],
                    has_elevator=profile["has_elevator"],
                    entry_code=profile["entry_code"],
                    notes=profile["notes"],
                    monthly_rate=profile["monthly_rate"],
                )
                db.add(building)
                db.flush()
                area_buildings.append(building)
                counts["buildings_seeded"] += 1

        all_buildings_by_area[area.id] = area_buildings

    db.flush()

    # -------------------------------------------------------------------------
    # Cleaning schedules
    # -------------------------------------------------------------------------
    for area in area_objects:
        for building in all_buildings_by_area[area.id]:
            if db.query(CleaningSchedule).filter(CleaningSchedule.building_id == building.id).count() == 0:
                rng = _det_rand(f"schedule:{building.address_text}")
                for sched in _cleaning_schedule_for_building(rng, building.id):
                    db.add(CleaningSchedule(**sched))
                    counts["cleaning_schedules_seeded"] += 1

    db.flush()

    # Build schedule lookup: building_id → set of db_dow values scheduled
    all_schedules = db.query(CleaningSchedule).all()
    building_scheduled_days: dict[int, set[int]] = {}
    building_sched_time: dict[int, str] = {}
    for sched in all_schedules:
        building_scheduled_days.setdefault(sched.building_id, set()).add(sched.day_of_week)
        if sched.building_id not in building_sched_time:
            building_sched_time[sched.building_id] = sched.time

    # -------------------------------------------------------------------------
    # Cleaning workers + assignments
    # -------------------------------------------------------------------------
    # worker_phone_counter must be deterministic
    worker_phone_counter = 4_000_000

    # area_idx → list of CleaningWorker objects in worker_idx order
    workers_by_area: dict[int, list[CleaningWorker]] = {}

    for area_idx, area in enumerate(area_objects):
        area_buildings = all_buildings_by_area[area.id]
        area_workers: list[CleaningWorker] = []

        for worker_idx, worker_name in enumerate(WORKER_NAMES[area_idx]):
            worker_phone = f"+97250{worker_phone_counter:07d}"
            worker_phone_counter += 1

            existing_worker = db.query(CleaningWorker).filter(CleaningWorker.phone_number == worker_phone).first()
            if existing_worker:
                worker = existing_worker
                if worker.area_id is None:
                    worker.area_id = area.id
            else:
                worker = CleaningWorker(
                    area_id=area.id,
                    name=worker_name,
                    phone_number=worker_phone,
                    is_active=True,
                )
                db.add(worker)
                db.flush()

            start = worker_idx * 10
            for building in area_buildings[start:start + 10]:
                if not db.query(BuildingWorkerAssignment).filter(
                    BuildingWorkerAssignment.building_id == building.id,
                    BuildingWorkerAssignment.worker_id == worker.id,
                    BuildingWorkerAssignment.is_current.is_(True),
                ).first():
                    db.add(BuildingWorkerAssignment(
                        building_id=building.id,
                        worker_id=worker.id,
                        is_current=True,
                        assigned_at=datetime(2026, 2, 1),
                    ))
            area_workers.append(worker)

        workers_by_area[area.id] = area_workers

    db.flush()

    # Flat maps
    all_workers: list[CleaningWorker] = [w for ws in workers_by_area.values() for w in ws]
    all_buildings_flat: dict[int, Building] = {
        b.id: b for buildings in all_buildings_by_area.values() for b in buildings
    }

    # worker → list of building ids (their assigned 10 buildings)
    worker_building_ids: dict[int, list[int]] = {}
    all_assignments = db.query(BuildingWorkerAssignment).filter(BuildingWorkerAssignment.is_current.is_(True)).all()
    for a in all_assignments:
        worker_building_ids.setdefault(a.worker_id, []).append(a.building_id)

    # -------------------------------------------------------------------------
    # User accounts
    # -------------------------------------------------------------------------
    # Area managers
    area_mgr_password = hash_password("demo123")
    for area, area_cfg in zip(area_objects, AREAS_CONFIG):
        username = area_cfg["username"]
        if not db.query(User).filter(User.username == username).first():
            db.add(User(
                username=username,
                hashed_password=area_mgr_password,
                full_name=area_cfg["manager"]["name"],
                role=UserRole.AREA_MANAGER,
                company_id=company.id,
                area_id=area.id,
                is_active=True,
            ))
            counts["users_seeded"] += 1

    # Workers
    worker_password = hash_password("worker123")
    for global_idx, worker in enumerate(all_workers, 1):
        username = f"worker_{global_idx:02d}"
        if not db.query(User).filter(User.username == username).first():
            db.add(User(
                username=username,
                hashed_password=worker_password,
                full_name=worker.name,
                role=UserRole.WORKER,
                company_id=company.id,
                worker_id=worker.id,
                area_id=worker.area_id,
                is_active=True,
            ))
            counts["users_seeded"] += 1

    db.flush()

    # -------------------------------------------------------------------------
    # Tickets — March 1 to April 11, 2026
    # -------------------------------------------------------------------------
    if db.query(Ticket).count() == 0:
        rng = random.Random(42)
        sla_hours_map = {
            TicketCategory.CLEANING: 24,
            TicketCategory.ELECTRIC: 6,
            TicketCategory.PLUMBING: 4,
            TicketCategory.ELEVATOR: 2,
            TicketCategory.GENERAL: 24,
        }

        # March: 100 tickets — 65% DONE, 15% IN_PROGRESS, 20% OPEN
        # April 1-11: 40 tickets — 25% DONE, 25% IN_PROGRESS, 50% OPEN
        ticket_batches = [
            # (count, period_start, period_end, done_pct, in_progress_pct)
            (100, datetime(2026, 3, 1), datetime(2026, 3, 31, 23, 59), 0.65, 0.15),
            (40,  datetime(2026, 4, 1), datetime(2026, 4, 11, 23, 59), 0.25, 0.25),
        ]

        for total, period_start, period_end, done_pct, ip_pct in ticket_batches:
            period_span_hours = int((period_end - period_start).total_seconds() / 3600)

            for i in range(total):
                area_idx = i % len(area_objects)
                area = area_objects[area_idx]
                building = rng.choice(all_buildings_by_area[area.id])
                resident = _resident_for(area_idx, rng.randint(0, 4))
                template = rng.choice(TICKET_TEMPLATES)
                category = template["category"]
                urgency = template["urgency"]

                r_status = rng.random()
                if r_status < done_pct:
                    status = TicketStatus.DONE
                elif r_status < done_pct + ip_pct:
                    status = TicketStatus.IN_PROGRESS
                else:
                    status = TicketStatus.OPEN

                sla_h = sla_hours_map[category]
                hours_offset = rng.randint(0, period_span_hours)
                created_at = period_start + timedelta(hours=hours_offset, minutes=rng.randint(0, 59))

                completed_at = None
                if status == TicketStatus.DONE:
                    fix_hours = max(1, int(sla_h * rng.uniform(0.3, 1.5)))
                    completed_at = min(created_at + timedelta(hours=fix_hours), period_end)

                floor = rng.randint(1, max(2, building.num_floors or 5))
                description = template["text"].format(floor=floor)

                ticket = Ticket(
                    area_id=area.id,
                    building_id=building.id,
                    building_text_raw=building.address_text,
                    resident_phone=resident["phone"],
                    category=category,
                    urgency=urgency.value,
                    status=status,
                    assigned_supplier_id=supplier_by_category.get(category, None) and supplier_by_category[category].id,
                    description=description,
                    created_at=created_at,
                    updated_at=completed_at or created_at,
                    sla_due_at=compute_sla_due_at(category, created_at),
                    completed_at=completed_at,
                )
                db.add(ticket)
                db.flush()
                ticket.public_id = f"TCK-{ticket.id:04d}"
                counts["tickets_seeded"] += 1

    db.commit()

    # -------------------------------------------------------------------------
    # Worker day swaps — 2 per area in March 2026
    # -------------------------------------------------------------------------
    # Specific pre-defined swaps for each area (deterministic, memorable)
    swap_specs = [
        # (area_idx, worker_idx_original, worker_idx_replacement, swap_date, reason)
        (0, 0, 1, date(2026, 3, 10), "מחלה"),
        (0, 2, 4, date(2026, 3, 18), "חיסור אישי"),
        (1, 0, 2, date(2026, 3, 6),  "מחלה"),
        (1, 3, 1, date(2026, 3, 24), "חיסור"),
        (2, 1, 3, date(2026, 3, 12), "מחלה"),
        (2, 4, 0, date(2026, 3, 26), "חיסור אישי"),
        (3, 0, 4, date(2026, 3, 11), "מחלה"),
        (3, 2, 1, date(2026, 3, 25), "חיסור"),
        (4, 1, 2, date(2026, 3, 9),  "מחלה"),
        (4, 3, 0, date(2026, 3, 23), "חיסור אישי"),
    ]

    for area_idx, orig_idx, repl_idx, swap_date, reason in swap_specs:
        area = area_objects[area_idx]
        area_workers_list = workers_by_area[area.id]
        if orig_idx >= len(area_workers_list) or repl_idx >= len(area_workers_list):
            continue

        orig_worker = area_workers_list[orig_idx]
        repl_worker = area_workers_list[repl_idx]

        # Find a building assigned to the original worker
        orig_buildings = worker_building_ids.get(orig_worker.id, [])
        if not orig_buildings:
            continue
        building_id = orig_buildings[0]  # first building of this worker

        swap_dt = datetime.combine(swap_date, datetime.min.time())
        swap_dt_end = swap_dt + timedelta(days=1)

        existing_swap = db.query(WorkerDaySwap).filter(
            WorkerDaySwap.building_id == building_id,
            WorkerDaySwap.date >= swap_dt,
            WorkerDaySwap.date < swap_dt_end,
        ).first()

        if not existing_swap:
            db.add(WorkerDaySwap(
                date=swap_dt,
                building_id=building_id,
                original_worker_id=orig_worker.id,
                replacement_worker_id=repl_worker.id,
                reason=reason,
            ))
            counts["swaps_seeded"] += 1

    db.flush()

    # Build swap lookup: (worker_id, date) → (building_id, is_original, replacement_worker_id)
    # original workers should NOT clock in; replacement workers clock in with is_swap_day=True
    all_swaps = db.query(WorkerDaySwap).all()
    # absent_on[worker_id][date] = building_id (worker was replaced, shouldn't clock in)
    absent_on: dict[int, dict[date, int]] = {}
    # swap_in[worker_id][date] = building_id (worker is replacement, clocks in with is_swap=True)
    swap_in: dict[int, dict[date, int]] = {}
    for swap in all_swaps:
        swap_date_d = swap.date.date() if isinstance(swap.date, datetime) else swap.date
        absent_on.setdefault(swap.original_worker_id, {})[swap_date_d] = swap.building_id
        swap_in.setdefault(swap.replacement_worker_id, {})[swap_date_d] = swap.building_id

    # -------------------------------------------------------------------------
    # Attendance records — March 1 to April 7, 2026
    # -------------------------------------------------------------------------
    working_days = _demo_working_days()

    for work_date in working_days:
        db_dow = (work_date.weekday() + 1) % 7  # Sun=0 … Sat=6
        work_dt = datetime.combine(work_date, datetime.min.time())

        for worker in all_workers:
            # Check if there's already a record for this worker/day
            existing_rec = db.query(AttendanceRecord).filter(
                AttendanceRecord.worker_id == worker.id,
                AttendanceRecord.work_date == work_dt,
            ).first()
            if existing_rec:
                continue

            rng = _det_rand(f"att:{worker.id}:{work_date.isoformat()}")

            # Was this worker replaced today? → skip (absent)
            if work_date in absent_on.get(worker.id, {}):
                continue

            # Is this worker covering a swap today?
            swap_building_id = swap_in.get(worker.id, {}).get(work_date)

            if swap_building_id:
                # Clock in at the swap building
                building = all_buildings_flat.get(swap_building_id)
                if not building:
                    continue
                sched_time = building_sched_time.get(swap_building_id, "07:30")
                is_swap = True
            else:
                # Find worker's buildings scheduled today
                my_building_ids = worker_building_ids.get(worker.id, [])
                scheduled_today = [
                    bid for bid in my_building_ids
                    if db_dow in building_scheduled_days.get(bid, set())
                ]
                if not scheduled_today:
                    continue

                # 8% absence rate for regular days
                if rng.random() < 0.08:
                    continue

                building_id = rng.choice(scheduled_today)
                building = all_buildings_flat.get(building_id)
                if not building:
                    continue
                sched_time = building_sched_time.get(building_id, "07:30")
                is_swap = False

            # Clock-in time: schedule time ± 15 minutes
            hour, minute = map(int, sched_time.split(":"))
            offset_min = rng.randint(-15, 20)
            total_minutes = hour * 60 + minute + offset_min
            clock_in_dt = work_dt + timedelta(minutes=total_minutes)

            # Duration: 3.5–5.5 hours
            duration_min = int(rng.uniform(210, 330))
            clock_out_dt = clock_in_dt + timedelta(minutes=duration_min)

            # GPS: near building coordinates
            base_lat = building.latitude or 32.07
            base_lng = building.longitude or 34.78
            lat_in = round(base_lat + rng.uniform(-0.0005, 0.0005), 6)
            lng_in = round(base_lng + rng.uniform(-0.0005, 0.0005), 6)
            lat_out = round(lat_in + rng.uniform(-0.0002, 0.0002), 6)
            lng_out = round(lng_in + rng.uniform(-0.0002, 0.0002), 6)

            db.add(AttendanceRecord(
                worker_id=worker.id,
                building_id=building.id,
                work_date=work_dt,
                clock_in_at=clock_in_dt,
                clock_out_at=clock_out_dt,
                clock_in_lat=lat_in,
                clock_in_lng=lng_in,
                clock_out_lat=lat_out,
                clock_out_lng=lng_out,
                is_swap_day=is_swap,
            ))
            counts["attendance_seeded"] += 1

    db.flush()

    # -------------------------------------------------------------------------
    # Workday deductions — 2 per area
    # -------------------------------------------------------------------------
    admin_user = db.query(User).filter(User.username == "admin").first()
    deduction_specs = [
        # (area_idx, worker_idx, building_offset, deduction_date, reason)
        (0, 1, 0, date(2026, 3, 16), "לא הגיע לעבודה למרות אישור נוכחות"),
        (0, 3, 1, date(2026, 3, 30), "ניקיון לא בוצע לפי סטנדרט"),
        (1, 0, 0, date(2026, 3, 13), "לא הגיע לעבודה"),
        (1, 2, 2, date(2026, 3, 27), "ניקיון חלקי בלבד"),
        (2, 1, 0, date(2026, 3, 19), "לא הגיע לעבודה"),
        (2, 4, 1, date(2026, 4, 1),  "ניקיון לא בוצע"),
        (3, 0, 0, date(2026, 3, 17), "לא הגיע לעבודה"),
        (3, 3, 2, date(2026, 3, 31), "ניקיון חלקי"),
        (4, 2, 0, date(2026, 3, 20), "לא הגיע לעבודה"),
        (4, 4, 1, date(2026, 4, 6),  "ניקיון לא בוצע לפי סטנדרט"),
    ]

    for area_idx, worker_idx, bldg_offset, ded_date, reason in deduction_specs:
        area = area_objects[area_idx]
        area_workers_list = workers_by_area[area.id]
        if worker_idx >= len(area_workers_list):
            continue
        worker = area_workers_list[worker_idx]
        worker_bldgs = worker_building_ids.get(worker.id, [])
        if bldg_offset >= len(worker_bldgs):
            continue
        building_id = worker_bldgs[bldg_offset]

        ded_dt = datetime.combine(ded_date, datetime.min.time())
        existing_ded = db.query(WorkdayDeduction).filter(
            WorkdayDeduction.worker_id == worker.id,
            WorkdayDeduction.building_id == building_id,
            WorkdayDeduction.work_date == ded_dt,
        ).first()

        if not existing_ded:
            db.add(WorkdayDeduction(
                worker_id=worker.id,
                building_id=building_id,
                work_date=ded_dt,
                reason=reason,
                deducted_by_user_id=admin_user.id if admin_user else None,
            ))
            counts["deductions_seeded"] += 1

    db.commit()
    return counts
