import re

from app.models import TicketCategory, TicketStatus


CATEGORY_KEYWORDS: dict[TicketCategory, list[str]] = {
    TicketCategory.CLEANING: ["cleaning", "ניקיון", "לכלוך", "lobby dirty", "dirty lobby"],
    TicketCategory.ELECTRIC: ["electric", "חשמל", "light", "תאורה"],
    TicketCategory.PLUMBING: ["plumbing", "אינסטלציה", "מים", "leak", "נזילה"],
    TicketCategory.ELEVATOR: ["elevator", "מעלית"],
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
    ]

    for pattern in patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            return extracted if extracted else None

    fallback = re.search(r"([A-Za-zא-ת\-\s]+\s\d{1,4})", stripped)
    if fallback:
        extracted = fallback.group(1).strip()
        return extracted if extracted else None

    return None


def extract_supplier_status(text: str) -> TicketStatus | None:
    normalized = _normalize(text)

    done_keywords = ["בוצע", "done"]
    in_progress_keywords = ["בטיפול", "in progress"]

    if any(keyword in normalized for keyword in done_keywords):
        return TicketStatus.DONE
    if any(keyword in normalized for keyword in in_progress_keywords):
        return TicketStatus.IN_PROGRESS

    return None
