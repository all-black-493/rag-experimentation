"""Dates as documents write them, put in order."""

import re
from datetime import date

from app.analysis.models import Event

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}

# "18th April 2025", "3rd day of February 2024", "12 August 2025", "April 25, 2025"
_DAY_FIRST = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?([A-Za-z]{3,9})\.?,?\s+((?:19|20)\d\d)\b"
)
_MONTH_FIRST = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:19|20)\d\d)\b")
_MONTH_YEAR = re.compile(r"\b([A-Za-z]{3,9})\.?\s+((?:19|20)\d\d)\b")
_ISO = re.compile(r"\b((?:19|20)\d\d)-(\d\d)-(\d\d)\b")


def parse_date(text: str) -> date | None:
    """The first date the wording names; a month alone becomes its first day."""
    if m := _ISO.search(text):
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    for pattern, order in ((_DAY_FIRST, (1, 2)), (_MONTH_FIRST, (2, 1))):
        for m in pattern.finditer(text):
            month = _MONTHS.get(m[order[1]].lower())
            if month:
                try:
                    return date(int(m[3]), month, int(m[order[0]]))
                except ValueError:
                    continue
    if m := _MONTH_YEAR.search(text):
        month = _MONTHS.get(m[1].lower())
        if month:
            return date(int(m[2]), month, 1)
    return None


def order_events(events: list[Event]) -> list[Event]:
    """Dated events in date order, then the undated in the order they came."""
    dated = []
    for event in events:
        parsed = parse_date(event.when) or parse_date(event.description)
        dated.append(event.model_copy(update={"date": parsed.isoformat() if parsed else None}))
    return sorted(dated, key=lambda e: (e.date is None, e.date or ""))
