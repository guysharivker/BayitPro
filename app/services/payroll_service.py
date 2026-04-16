"""
Payroll calculation helpers.

Working-day convention (Israeli): Sunday–Thursday, excluding public holidays.
Friday and Saturday are always excluded.
"""

import calendar
from datetime import date, datetime, timedelta

# Israeli public holidays (working days only — Fri/Sat already excluded).
# Extend this set as needed.
_ISRAELI_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 4, 14),  # Erev Pesach (half-day → treat as holiday)
    date(2025, 4, 15),  # Pesach I
    date(2025, 4, 16),  # Pesach II
    date(2025, 4, 21),  # Pesach VII
    date(2025, 4, 23),  # Yom HaZikaron
    date(2025, 4, 24),  # Yom HaAtzmaut
    date(2025, 6, 2),   # Shavuot
    date(2025, 9, 22),  # Rosh Hashana I
    date(2025, 9, 23),  # Rosh Hashana II
    date(2025, 10, 1),  # Yom Kippur
    date(2025, 10, 6),  # Sukkot I
    date(2025, 10, 13), # Shmini Atzeret
    # 2026
    date(2026, 3, 5),   # Purim (Thu)
    date(2026, 4, 2),   # Pesach I (Thu)
    date(2026, 4, 8),   # Pesach VII (Wed)
    date(2026, 4, 9),   # Pesach VIII (Thu)
    date(2026, 4, 20),  # Yom HaZikaron (Mon)
    date(2026, 4, 21),  # Yom HaAtzmaut (Tue)
    date(2026, 5, 21),  # Shavuot (Thu)
    date(2026, 9, 10),  # Rosh Hashana I (Thu)
    date(2026, 9, 24),  # Sukkot I (Thu)
    date(2026, 10, 1),  # Shmini Atzeret (Thu)
}


def is_working_day(d: date) -> bool:
    """True if d is a billable working day (Sun–Thu, not a holiday)."""
    if d.weekday() in (4, 5):  # Fri=4, Sat=5
        return False
    return d not in _ISRAELI_HOLIDAYS


def working_days_in_month(year: int, month: int) -> int:
    """Count billable working days in the given month."""
    _, days_in_month = calendar.monthrange(year, month)
    return sum(
        1 for day in range(1, days_in_month + 1)
        if is_working_day(date(year, month, day))
    )


def daily_rate(monthly_rate: float, year: int, month: int) -> float:
    """Daily rate = monthly_rate / working_days_in_month."""
    wd = working_days_in_month(year, month)
    if wd == 0:
        return 0.0
    return round(monthly_rate / wd, 4)


def month_boundaries(year: int, month: int) -> tuple[datetime, datetime]:
    """Return (first_moment, last_moment_exclusive) for a calendar month."""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def _next_month_date(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def revenue_for_building(monthly_rate: float, from_date: date, to_date: date) -> float:
    """
    Prorate monthly_rate over [from_date, to_date] by working days.
    Handles partial months and multi-month ranges correctly.
    """
    if not monthly_rate or monthly_rate <= 0:
        return 0.0

    total = 0.0
    cursor = from_date.replace(day=1)

    while cursor <= to_date:
        year, month = cursor.year, cursor.month
        wd_total = working_days_in_month(year, month)
        if wd_total > 0:
            _, days_in_month = calendar.monthrange(year, month)
            month_start = max(from_date, date(year, month, 1))
            month_end = min(to_date, date(year, month, days_in_month))
            wd_in_range = sum(
                1 for offset in range((month_end - month_start).days + 1)
                if is_working_day(month_start + timedelta(days=offset))
            )
            total += (monthly_rate / wd_total) * wd_in_range

        cursor = _next_month_date(cursor)

    return round(total, 2)
