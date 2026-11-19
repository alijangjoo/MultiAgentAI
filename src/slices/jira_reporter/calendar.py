"""Vendor team work week: Saturday through Wednesday."""

from __future__ import annotations

from datetime import date, datetime, timedelta

# Python weekday: Monday=0 ... Sunday=6. Workdays are Sat, Sun, Mon, Tue, Wed.
_WORKDAYS = {5, 6, 0, 1, 2}


def is_workday(day: date) -> bool:
    return day.weekday() in _WORKDAYS


def business_days_inclusive(start: date, end: date) -> int:
    """Count workdays from start through end, including both ends when they are workdays."""
    if end < start:
        return 0
    count = 0
    day = start
    while day <= end:
        if is_workday(day):
            count += 1
        day += timedelta(days=1)
    return count


def parse_jira_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None