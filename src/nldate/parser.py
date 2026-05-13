"""
nldate/parser.py
Natural language date parser.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional, Any, cast


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_WRITTEN_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def _resolve_number(s: str) -> int:
    """Convert a string like '3', 'three', 'a', 'an' to an integer."""
    s = s.strip().lower()
    if s in ("a", "an"):
        return 1
    if s.isdigit():
        return int(s)
    return _WRITTEN_NUMBERS[s]


def _clean(s: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", s.strip().lower())


# ---------------------------------------------------------------------------
# Individual parsers  (each returns date | None)
# ---------------------------------------------------------------------------


def _parse_today_tomorrow_yesterday(s: str, today: date) -> Optional[date]:
    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s == "yesterday":
        return today - timedelta(days=1)
    return None


# "next tuesday", "last monday", "this friday"
_WEEKDAY_RE = re.compile(r"^(next|last|this)\s+(" + "|".join(_WEEKDAYS) + r")$")


def _parse_relative_weekday(s: str, today: date) -> Optional[date]:
    m = _WEEKDAY_RE.match(s)
    if not m:
        return None
    direction, day_name = m.group(1), m.group(2)
    target_wd = _WEEKDAYS[day_name]
    current_wd = today.weekday()

    if direction == "next":
        delta = (target_wd - current_wd) % 7
        if delta == 0:
            delta = 7  # "next monday" when today IS monday → next week
        return today + timedelta(days=delta)
    elif direction == "last":
        delta = (current_wd - target_wd) % 7
        if delta == 0:
            delta = 7
        return today - timedelta(days=delta)
    else:  # "this"
        delta = (target_wd - current_wd) % 7
        return today + timedelta(days=delta)


# Absolute: "Dec 1, 2025" / "1 Dec 2025" / "December 1 2025" / "2025-12-01" / "12/01/2025"
_ABS_MONTH_NAME_RE = re.compile(
    r"^(?:(\d{1,2})\s+)?("
    + "|".join(_MONTHS)
    + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$"
)
_ABS_MONTH_NAME_RE2 = re.compile(
    r"^(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})$"
)
_ABS_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ABS_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_ABS_DAY_MONTH_YEAR_RE = re.compile(
    r"^(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\.?\s+(\d{4})$"
)


def _parse_absolute(s: str) -> Optional[date]:
    # ISO
    m = _ABS_ISO_RE.match(s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # MM/DD/YYYY
    m = _ABS_SLASH_RE.match(s)
    if m:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))

    # "Dec 1, 2025" / "December 1 2025"
    m = _ABS_MONTH_NAME_RE2.match(s)
    if m:
        month = _MONTHS[m.group(1)]
        day = int(m.group(2))
        year = int(m.group(3))
        return date(year, month, day)

    # "1 Dec 2025" / "1st December 2025"
    m = _ABS_DAY_MONTH_YEAR_RE.match(s)
    if m:
        day = int(m.group(1))
        month = _MONTHS[m.group(2)]
        year = int(m.group(3))
        return date(year, month, day)

    return None


# ---------------------------------------------------------------------------
# Offset building blocks
# ---------------------------------------------------------------------------

_NUM_PAT = r"(\d+|" + "|".join(_WRITTEN_NUMBERS) + r"|a|an)"
_UNIT_PAT = r"(years?|months?|weeks?|days?)"
_CHUNK_RE = re.compile(rf"{_NUM_PAT}\s+{_UNIT_PAT}", re.IGNORECASE)


def _apply_chunks(base: date, chunks: list[tuple[str, str]], forward: bool) -> date:
    rd_kwargs: dict[str, int] = {}
    td_days = 0
    for num_s, unit_s in chunks:
        n = _resolve_number(num_s)
        u = unit_s.lower().rstrip("s")  # normalise plural
        if u == "year":
            rd_kwargs["years"] = rd_kwargs.get("years", 0) + n
        elif u == "month":
            rd_kwargs["months"] = rd_kwargs.get("months", 0) + n
        elif u == "week":
            td_days += n * 7
        elif u == "day":
            td_days += n
    sign = 1 if forward else -1
    rd_args: Any = {k: v * sign for k, v in rd_kwargs.items()}
    result = base + relativedelta(**cast(Any, rd_args))
    result += timedelta(days=td_days * sign)
    return result


# "3 days after tomorrow" / "2 weeks before Dec 1, 2025"
_OFFSET_RE = re.compile(
    r"^(.*?)\s+(before|after|from|ago|later|hence)\s+(.+)$",
    re.IGNORECASE,
)

# "in 3 days" / "3 days ago" / "3 days from now" / "3 days later"
_SIMPLE_OFFSET_RE = re.compile(
    rf"^(?:in\s+)?({_NUM_PAT}\s+{_UNIT_PAT}(?:\s+and\s+{_NUM_PAT}\s+{_UNIT_PAT})*)\s*(ago|from now|from today|later|hence)?$",
    re.IGNORECASE,
)


def _parse_offset(s: str, today: date) -> Optional[date]:
    # "in 3 days", "3 days ago", "3 weeks from now"
    m = _SIMPLE_OFFSET_RE.match(s)
    if m:
        chunk_str = m.group(1)
        suffix = (m.group(m.lastindex) if m.lastindex is not None else "")
        suffix = suffix.lower()
        chunks = _CHUNK_RE.findall(chunk_str)
        if chunks:
            forward = suffix not in ("ago",)
            return _apply_chunks(today, chunks, forward)

    # "X days/months/... before/after <anchor>"
    m = _OFFSET_RE.match(s)
    if m:
        offset_part = m.group(1).strip()
        direction = m.group(2).lower()
        anchor_part = m.group(3).strip()

        # resolve anchor recursively
        anchor = parse(anchor_part, today=today)

        chunks = _CHUNK_RE.findall(offset_part)
        if chunks:
            forward = direction in ("after", "from", "later", "hence")
            return _apply_chunks(anchor, chunks, forward)

    return None


# ---------------------------------------------------------------------------
# Combinations: "X years and Y months after ..."
# (already handled by _parse_offset + _CHUNK_RE multi-chunk, but kept explicit)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(s: str, today: Optional[date] = None) -> date:
    """
    Parse a natural language date string and return a ``datetime.date``.

    Parameters
    ----------
    s:
        Natural language date string, e.g. ``"next Tuesday"``,
        ``"3 days before Dec 1, 2025"``, ``"2 years and 3 months after today"``.
    today:
        The reference date for relative expressions.  Defaults to
        ``date.today()`` when *None*.

    Returns
    -------
    date

    Raises
    ------
    ValueError
        If the string cannot be parsed.
    """
    if today is None:
        today = date.today()

    cleaned = _clean(s)

    # 1. Simple keywords
    result = _parse_today_tomorrow_yesterday(cleaned, today)
    if result is not None:
        return result

    # 2. Relative weekday
    result = _parse_relative_weekday(cleaned, today)
    if result is not None:
        return result

    # 3. Absolute date
    result = _parse_absolute(cleaned)
    if result is not None:
        return result

    # 4. Offset (handles combinations via multi-chunk regex)
    result = _parse_offset(cleaned, today)
    if result is not None:
        return result

    raise ValueError(f"Cannot parse date string: {s!r}")
