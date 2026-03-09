"""
Parse a TeamUp ICS feed into CalendarEvents.

Two public functions are provided:

get_time_blocks(ics_path, subject_keyword)
    Scan the ICS for events whose SUMMARY contains *subject_keyword* and
    return a mapping of date → (start_time, duration_hours).
    Used by subject sources (e.g. SAWSource) to enrich their all-day events
    with the real time blocks that TeamUp knows about.

parse_teamup_events(ics_path, skip_subjects, date_from)
    Parse all VEVENTs in the ICS, skipping those whose cleaned SUMMARY
    starts with any of the strings in *skip_subjects* (case-insensitive),
    and optionally skipping events before *date_from*.

    The DESCRIPTION field contains a group token on its last non-empty line
    (e.g. "GR1", "GR2", "GG").  This is mapped as:
        GG  → groups={"GR1", "GR2"}   (whole-class, visible to both groups)
        GR1 → groups={"GR1"}
        GR2 → groups={"GR2"}
        *   → groups={"ALL"}            (catch-all for unrecognised tokens)
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar  # type: ignore[import-untyped]

from models import CalendarEvent

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Madrid")

# Strip the " (email@uma.es)" suffix that TeamUp appends to every SUMMARY.
_EMAIL_SUFFIX = re.compile(r"\s*\([^)]+@[^)]+\)\s*$")


def _clean_summary(raw: str) -> str:
    """'Probabilidad y Estadística (sixto@uma.es)' → 'Probabilidad y Estadística'"""
    return _EMAIL_SUFFIX.sub("", raw).strip()


def _to_local_datetime(dt_value: object) -> datetime | None:
    """Coerce an icalendar DTSTART/DTEND value to a timezone-aware datetime."""
    if isinstance(dt_value, datetime):
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=TIMEZONE)
        return dt_value.astimezone(TIMEZONE)
    if isinstance(dt_value, date):
        # All-day value (DATE, not DATETIME) — not useful for time blocks.
        return None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_time_blocks(
    ics_path: Path,
    subject_keyword: str,
) -> dict[date, tuple[tuple[int, int], int]]:
    """
    Scan *ics_path* for events whose SUMMARY contains *subject_keyword* and
    return a mapping:

        date  →  ((hour, minute), duration_hours)

    If multiple events for the same subject fall on the same date (unlikely),
    the last one processed wins.
    """
    with ics_path.open("rb") as f:
        cal = Calendar.from_ical(f.read())

    blocks: dict[date, tuple[tuple[int, int], int]] = {}
    keyword_lower = subject_keyword.lower()

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        summary = str(component.get("SUMMARY", ""))
        if keyword_lower not in summary.lower():
            continue

        dtstart = _to_local_datetime(component.get("DTSTART").dt)
        dtend = _to_local_datetime(component.get("DTEND").dt)
        if dtstart is None or dtend is None:
            continue

        duration_hours = math.ceil((dtend - dtstart).total_seconds() / 3600)
        blocks[dtstart.date()] = ((dtstart.hour, dtstart.minute), duration_hours)

    logger.info(
        "Extracted %d time block(s) for %r from %s.",
        len(blocks),
        subject_keyword,
        ics_path.name,
    )
    return blocks


_GROUP_MAP: dict[str, set[str]] = {
    "GR1": {"GR1"},
    "GR2": {"GR2"},
    "GG": {"GR1", "GR2"},
}


def _groups_from_description(description: str) -> set[str]:
    """
    Extract the group token from a VEVENT DESCRIPTION string.

    TeamUp stores attendance info in the last non-empty line of the field:
        "Who: email@uma.es\n\nGR1\n\n"  →  "GR1"

    Maps:
        GR1  → {"GR1"}
        GR2  → {"GR2"}
        GG   → {"GR1", "GR2"}
        else → {"ALL"}   (catch-all for unrecognised / split tokens)
    """
    lines = [ln.strip() for ln in description.splitlines()]
    # Walk backwards to find the last non-empty line that is not the Who: header.
    for line in reversed(lines):
        if not line or line.lower().startswith("who:"):
            continue
        token = line.upper()
        return _GROUP_MAP.get(token, {"ALL"})
    return {"ALL"}


def parse_teamup_events(
    ics_path: Path,
    skip_subjects: set[str],
    date_from: date | None = None,
) -> list[CalendarEvent]:
    """
    Parse all VEVENTs in *ics_path*, skipping any whose cleaned SUMMARY
    starts with a string in *skip_subjects* (case-insensitive prefix match),
    and optionally those before *date_from*.

    The DESCRIPTION group token is parsed and mapped to ``groups``:
        GG  → {"GR1", "GR2"},  GR1 → {"GR1"},  GR2 → {"GR2"}
    Unrecognised tokens fall back to {"ALL"}.
    """
    with ics_path.open("rb") as f:
        cal = Calendar.from_ical(f.read())

    skip_lower = {s.lower() for s in skip_subjects}
    events: list[CalendarEvent] = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        raw_summary = str(component.get("SUMMARY", ""))
        subject = _clean_summary(raw_summary)

        # Skip subjects handled by dedicated sources.
        subject_lower = subject.lower()
        if any(subject_lower.startswith(s) for s in skip_lower):
            continue

        dtstart = _to_local_datetime(component.get("DTSTART").dt)
        dtend = _to_local_datetime(component.get("DTEND").dt)
        if dtstart is None:
            continue

        # Q2 date filter.
        if date_from is not None and dtstart.date() < date_from:
            continue

        duration_hours = 1
        if dtend is not None:
            duration_hours = max(1, math.ceil((dtend - dtstart).total_seconds() / 3600))

        location = str(component.get("LOCATION", "")).strip()
        description = str(component.get("DESCRIPTION", ""))
        groups = _groups_from_description(description)

        # [T] for whole-class (GG / ALL), [P] for group-specific sessions.
        if groups == {"GR1", "GR2"} or groups == {"ALL"}:
            prefix = "[T]"
        else:
            prefix = "[P]"
        summary = f"{prefix} {subject}"

        events.append(
            CalendarEvent(
                subject=subject,
                date=dtstart.date(),
                summary=summary,
                description="",
                location=location,
                groups=groups,
                time=(dtstart.hour, dtstart.minute),
                duration_hours=duration_hours,
            )
        )

    logger.info(
        "Parsed %d TeamUp event(s) from %s (skipped: %s, date_from: %s).",
        len(events),
        ics_path.name,
        ", ".join(sorted(skip_subjects)),
        date_from,
    )
    return events
