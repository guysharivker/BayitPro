import re

from app.models import TicketCategory, TicketStatus


CATEGORY_KEYWORDS: dict[TicketCategory, list[str]] = {
    TicketCategory.CLEANING: [
        "cleaning", "ניקיון", "ניקוי", "נקי", "נקיון", "לכלוך", "מלוכלך",
        "אשפה", "ריח", "lobby dirty", "dirty lobby", "שטיפה", "לנקות",
        "dirty", "garbage", "trash", "smell",
    ],
    TicketCategory.ELECTRIC: [
        "electric", "חשמל", "חשמלי", "light", "תאורה", "אור", "נורה",
        "חשוך", "חשכה", "שקע", "חיווט", "מנורה", "electricity",
    ],
    TicketCategory.PLUMBING: [
        "plumbing", "אינסטלציה", "מים", "נזילה", "נזיל", "מזגן", "צינור",
        "ברז", "סתימה", "הצפה", "ביוב", "שפכים", "leak", "pipe", "water",
        "flood", "blocked", "drain",
    ],
    TicketCategory.ELEVATOR: [
        "elevator", "מעלית", "לפט", "תקוע", "תקועה", "lift",
    ],
}


def _normalize(text: str) -> str:
    return text.strip().lower()


def classify_category(text: str) -> TicketCategory:
    normalized = _normalize(text)
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    return TicketCategory.GENERAL


def extract_ticket_reference_number(text: str) -> int | None:
    hash_match = re.search(r"#(\d+)", text)
    if hash_match:
        return int(hash_match.group(1))

    public_match = re.search(r"\bTCK-(\d{1,})\b", text, flags=re.IGNORECASE)
    if public_match:
        return int(public_match.group(1))

    return None


def extract_building_text(text: str) -> str | None:
    stripped = text.strip()

    patterns = [
        r"בניין\s+([^,\.\n]+)",
        r"building\s+([^,\.\n]+)",
        r"address\s+([^,\.\n]+)",
        # Israeli street address: street name + number (Hebrew or Latin)
        r"((?:רחוב\s+)?[א-ת\-\s]+\s+\d{1,4}(?:\s+(?:תל\s*אביב|ירושלים|חיפה|רמת\s*גן|גבעתיים|בני\s*ברק|פתח\s*תקוה|ראשון\s*לציון|הרצליה|כפר\s*סבא|נתניה|אשדוד|אשקלון|באר\s*שבע))?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            return extracted if extracted else None

    return None


def extract_supplier_status(text: str) -> TicketStatus | None:
    normalized = _normalize(text)

    done_keywords = ["בוצע", "הושלם", "טיפלתי", "סיימתי", "done", "completed", "finished"]
    in_progress_keywords = ["בטיפול", "מטפל", "מטפלת", "in progress", "working on"]

    if any(keyword in normalized for keyword in done_keywords):
        return TicketStatus.DONE
    if any(keyword in normalized for keyword in in_progress_keywords):
        return TicketStatus.IN_PROGRESS

    return None
