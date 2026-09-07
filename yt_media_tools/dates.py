"""Date and datetime literal parsing for the shared query language."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from .units import load_default_unit_registry


DateOrder = Literal["dmy", "mdy", "ymd"]

_MONTHS = {name.casefold(): number for number, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.casefold(): number for number, name in enumerate(calendar.month_abbr) if name})

_UNIT_TOKEN = r"[^\W\d_]+(?:-[^\W\d_]+)*"
_TEMPORAL_EXPR_RE = re.compile(
    rf"^(?P<base>TODAY|NOW)\(\)\s*(?:(?P<op>[+-])\s*(?P<count>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_TOKEN}))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DateContext:
    """Settings used when resolving human-readable date literals."""

    date_order: DateOrder = "dmy"
    now: datetime | None = None

    def __post_init__(self) -> None:
        # Capture the clock once so TODAY()/NOW() cannot drift during one query run.
        if self.now is None:
            object.__setattr__(self, "now", datetime.now().astimezone())

    @property
    def local_now(self) -> datetime:
        value = self.now
        assert value is not None
        if value.tzinfo is None:
            return value.astimezone()
        return value

    @property
    def today(self) -> date:
        return self.local_now.date()


def _normalise_spaces(text: str) -> str:
    return " ".join(text.strip().split())


def _calendar_shift_day(value: date, *, months: int = 0, years: int = 0) -> date:
    """Shift a date by calendar months/years, clamping the day when needed."""
    total_months = value.year * 12 + (value.month - 1) - months - years * 12
    year, month_index = divmod(total_months, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _calendar_shift(value: date | datetime, *, months: int = 0, years: int = 0) -> date | datetime:
    """Shift a date or datetime by calendar months/years, clamping the day when needed."""
    shifted = _calendar_shift_day(value.date() if isinstance(value, datetime) else value, months=months, years=years)
    if isinstance(value, datetime):
        return value.replace(year=shifted.year, month=shifted.month, day=shifted.day)
    return shifted


def parse_temporal_expression(text: str, context: DateContext, *, expected: str) -> date | datetime:
    """Parse TODAY()/NOW() with optional relative arithmetic and strict result typing."""
    raw = _normalise_spaces(text)
    match = _TEMPORAL_EXPR_RE.fullmatch(raw)
    if not match:
        raise ValueError(f"Could not understand temporal expression {raw!r}.")

    base = match.group("base").upper()
    if expected == "date" and base != "TODAY":
        raise ValueError("NOW() produces a timestamp. Use TODAY() for date comparisons.")
    if expected == "datetime" and base != "NOW":
        raise ValueError("TODAY() produces a date. Use NOW() for timestamp comparisons.")

    value: date | datetime = context.today if base == "TODAY" else context.local_now
    if match.group("op") is None:
        return value

    count_text = match.group("count")
    count = float(count_text)
    unit_text = match.group("unit")
    try:
        unit = load_default_unit_registry().resolve(unit_text)
    except ValueError as exc:
        raise ValueError(f"Unknown temporal unit {unit_text!r}.") from exc
    sign = -1 if match.group("op") == "-" else 1

    if unit.kind == "calendar":
        months = unit.amount * count
        if not months.is_integer():
            raise ValueError(f"Calendar unit {unit_text!r} requires a whole number of months.")
        return _calendar_shift(value, months=-(int(months) * sign))

    if expected == "date":
        days = unit.amount * count / 86400
        if not days.is_integer():
            raise ValueError(
                f"TODAY() date arithmetic does not support sub-day unit {unit_text!r}. "
                "Use a whole-day or calendar unit."
            )
        return value + timedelta(days=int(days) * sign)

    return value + timedelta(seconds=unit.amount * count * sign)


def parse_date_literal(text: str, context: DateContext) -> date:
    """Parse deterministic ISO, local, named-month, and relative date forms."""
    raw = _normalise_spaces(text)
    lowered = raw.casefold()

    if _TEMPORAL_EXPR_RE.fullmatch(raw):
        value = parse_temporal_expression(raw, context, expected="date")
        assert isinstance(value, date) and not isinstance(value, datetime)
        return value

    if lowered == "today":
        return context.today
    if lowered == "yesterday":
        return context.today - timedelta(days=1)
    if lowered == "tomorrow":
        return context.today + timedelta(days=1)

    relative = re.fullmatch(
        rf"(?P<count>\d+)\s+(?P<unit>{_UNIT_TOKEN})\s+ago",
        lowered,
    )
    if relative:
        count = int(relative.group("count"))
        unit_text = relative.group("unit")
        try:
            unit = load_default_unit_registry().resolve(unit_text)
        except ValueError as exc:
            raise ValueError(f"Unknown relative-date unit {unit_text!r}.") from exc
        if unit.kind == "calendar":
            months = unit.amount * count
            if not months.is_integer():
                raise ValueError(f"Calendar unit {unit_text!r} requires a whole number of months.")
            return _calendar_shift_day(context.today, months=int(months))
        days = unit.amount * count / 86400
        if not days.is_integer():
            raise ValueError(f"Relative date unit {unit_text!r} must resolve to a whole number of days.")
        return context.today - timedelta(days=int(days))

    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", raw)
    if compact:
        return _make_date(raw, *(int(part) for part in compact.groups()))

    year_first = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if year_first:
        return _make_date(raw, *(int(part) for part in year_first.groups()))

    local_numeric = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", raw)
    if local_numeric:
        first, second, year = (int(part) for part in local_numeric.groups())
        if context.date_order == "dmy":
            return _make_date(raw, year, second, first)
        if context.date_order == "mdy":
            return _make_date(raw, year, first, second)
        raise ValueError(f"Date {raw!r} is not year-first. Use YYYY-MM-DD or choose --date-format dmy/mdy.")

    named = re.fullmatch(
        r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})",
        raw,
        re.IGNORECASE,
    )
    if named:
        month_name = named.group("month").casefold()
        if month_name not in _MONTHS:
            raise ValueError(f"Unknown month name {named.group('month')!r}.")
        return _make_date(
            raw,
            int(named.group("year")),
            _MONTHS[month_name],
            int(named.group("day")),
        )

    named_us = re.fullmatch(
        r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(?P<year>\d{4})",
        raw,
        re.IGNORECASE,
    )
    if named_us:
        month_name = named_us.group("month").casefold()
        if month_name not in _MONTHS:
            raise ValueError(f"Unknown month name {named_us.group('month')!r}.")
        return _make_date(
            raw,
            int(named_us.group("year")),
            _MONTHS[month_name],
            int(named_us.group("day")),
        )

    raise ValueError(
        "Could not understand the date. Use ISO YYYY-MM-DD, YYYYMMDD, a configured local "
        "numeric date, a named date such as '1 January 2024', or a relative date such as "
        "'6 months ago'."
    )


def _make_date(raw: str, year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"Invalid date {raw!r}: {exc}.") from exc


def parse_datetime_literal(text: str, context: DateContext) -> datetime:
    """Parse an ISO datetime or a typed NOW() relative expression."""
    raw = _normalise_spaces(text)
    if _TEMPORAL_EXPR_RE.fullmatch(raw):
        value = parse_temporal_expression(raw, context, expected="datetime")
        assert isinstance(value, datetime)
        return value
    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            "Could not understand the timestamp. Use an ISO datetime such as "
            "2024-01-01T18:30:00Z, or NOW() with optional relative arithmetic."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=context.local_now.tzinfo)
    return parsed


def timestamp_to_datetime(value: object) -> object:
    """Normalise numeric epoch timestamps to UTC datetimes when possible."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return value
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return value
    return value
