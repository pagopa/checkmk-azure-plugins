"""UTC NCRONTAB evaluation using only the Python standard library."""

from bisect import bisect_right
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
import re


_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_WEEKDAYS = (
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
)
_MONTH_NAMES = {
    alias: number
    for number, name in enumerate(_MONTHS, 1)
    for alias in (name, name[:3])
}
_WEEKDAY_NAMES = {
    alias: number
    for number, name in enumerate(_WEEKDAYS)
    for alias in (name, name[:3])
}


def _parse_field(
    field: str, minimum: int, maximum: int, names: dict[str, int] | None = None,
) -> tuple[int, ...]:
    def value(text: str) -> int:
        if names is not None and text.lower() in names:
            number = names[text.lower()]
        elif re.fullmatch(r"[0-9]+", text):
            number = int(text)
        else:
            raise ValueError(f"Unsupported NCRONTAB value: {text!r}")
        if not minimum <= number <= maximum:
            raise ValueError(
                f"NCRONTAB value {text!r} is outside {minimum}..{maximum}"
            )
        return number

    values = set()
    for member in field.split(","):
        parts = member.split("/")
        if len(parts) > 2:
            raise ValueError(f"Invalid NCRONTAB field: {field!r}")
        base = parts[0]
        step = 1
        if len(parts) == 2:
            if not re.fullmatch(r"[0-9]+", parts[1]) or int(parts[1]) == 0:
                raise ValueError(f"Invalid NCRONTAB step: {member!r}")
            step = int(parts[1])
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            bounds = base.split("-")
            if len(bounds) != 2:
                raise ValueError(f"Invalid NCRONTAB range: {member!r}")
            start, end = (value(bound) for bound in bounds)
        else:
            start = value(base)
            end = maximum if len(parts) == 2 else start
        if start > end:
            raise ValueError(f"Reversed NCRONTAB range: {member!r}")
        values.update(range(start, end + 1, step))
    return tuple(sorted(values))


def previous_occurrence(expression: str, before: datetime) -> datetime:
    """Return the latest whole-second occurrence strictly before ``before``.

    Accept five fields (implicit second zero) or six fields (seconds first).
    All calendar constraints, including both day fields, must match. Input
    datetimes must be timezone-aware; evaluation and the result are in UTC.
    Invalid, unsupported or impossible schedules raise ValueError.
    """
    if not isinstance(expression, str):
        raise ValueError("NCRONTAB expression must be a string")
    fields = expression.split()
    if len(fields) == 5:
        fields.insert(0, "0")
    if len(fields) != 6:
        raise ValueError("NCRONTAB expression must contain five or six fields")
    seconds = _parse_field(fields[0], 0, 59)
    minutes = _parse_field(fields[1], 0, 59)
    hours = _parse_field(fields[2], 0, 23)
    days = _parse_field(fields[3], 1, 31)
    months = _parse_field(fields[4], 1, 12, _MONTH_NAMES)
    weekdays = _parse_field(fields[5], 0, 6, _WEEKDAY_NAMES)
    if not isinstance(before, datetime) or before.utcoffset() is None:
        raise ValueError("NCRONTAB evaluation requires a timezone-aware datetime")
    try:
        limit = before.astimezone(timezone.utc) - timedelta(microseconds=1)
    except OverflowError as error:
        raise ValueError("No previous occurrence in the supported datetime range") from error

    # Gregorian dates and weekdays repeat every 400 years. Skip disallowed
    # calendar fields rather than walking backwards second by second.
    for year in range(limit.year, max(0, limit.year - 401), -1):
        for month in reversed(months):
            if year == limit.year and month > limit.month:
                continue
            last_day = monthrange(year, month)[1]
            for day in reversed(days):
                if day > last_day:
                    continue
                candidate = date(year, month, day)
                if candidate > limit.date() or (candidate.weekday() + 1) % 7 not in weekdays:
                    continue
                same_day = candidate == limit.date()
                for hour in reversed(hours):
                    if same_day and hour > limit.hour:
                        continue
                    for minute in reversed(minutes):
                        same_hour = same_day and hour == limit.hour
                        if same_hour and minute > limit.minute:
                            continue
                        second_limit = (
                            limit.second if same_hour and minute == limit.minute else 59
                        )
                        index = bisect_right(seconds, second_limit) - 1
                        if index >= 0:
                            return datetime(
                                year, month, day, hour, minute, seconds[index],
                                tzinfo=timezone.utc,
                            )
    raise ValueError("No previous NCRONTAB occurrence within a 400-year calendar cycle")
