"""
Generic ICS exporter.

Accepts a list of CalendarEvent objects and a list of Profile configurations,
and writes one ICS file per profile.

A profile defines which group variant of each subject to include.  Events tagged
with ``groups={"ALL"}`` (e.g. TeamUp subjects shared by everyone) are always
included regardless of the profile.

Example — four files for all GR1/GR2 combinations across ISS and SAW::

    iss = "Ingeniería del Software Seguro"
    saw = "Seguridad en Aplicaciones Web"
    profiles = [
        Profile("ISS-GR1_SAW-GR1", {iss: "GR1", saw: "GR1"}),
        Profile("ISS-GR1_SAW-GR2", {iss: "GR1", saw: "GR2"}),
        Profile("ISS-GR2_SAW-GR1", {iss: "GR2", saw: "GR1"}),
        Profile("ISS-GR2_SAW-GR2", {iss: "GR2", saw: "GR2"}),
    ]
    export_ics(events, profiles, Path("."))
    # → calendar_ISS-GR1_SAW-GR1.ics, calendar_ISS-GR1_SAW-GR2.ics, …
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from models import CalendarEvent, Profile

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _new_calendar(name: str) -> Calendar:
    cal = Calendar()
    cal.add("prodid", f"-//CalendarCreator//{name}//ES")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "Europe/Madrid")
    return cal


def _build_ical_event(evt: CalendarEvent) -> Event:
    event = Event()
    event.add("uid", str(uuid.uuid4()))
    event.add("summary", evt.summary)
    event.add("description", evt.description)
    event.add("location", evt.location)

    if evt.time is None:
        # All-day event: DTSTART is a DATE value (no time component).
        event.add("dtstart", evt.date)
    else:
        start = datetime(
            evt.date.year,
            evt.date.month,
            evt.date.day,
            evt.time[0],
            evt.time[1],
            tzinfo=TIMEZONE,
        )
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(hours=evt.duration_hours))

    return event


def _event_in_profile(evt: CalendarEvent, profile: Profile) -> bool:
    """
    Return True if *evt* should be included in *profile*.

    Inclusion rules (in priority order):
      1. ``"ALL" in evt.groups`` — universal events always included.
      2. The profile has a group choice for ``evt.subject`` AND that choice
         is present in ``evt.groups``.
      3. The subject is not managed by this profile (not in ``profile.groups``)
         AND the event targets both groups (``{"GR1","GR2"} ⊆ evt.groups``)
         — i.e. a whole-class (GG) event for a subject without a split choice.
    """
    if "ALL" in evt.groups:
        return True
    chosen_group = profile.groups.get(evt.subject)
    if chosen_group is not None:
        return chosen_group in evt.groups
    # Subject not managed by this profile: include only whole-class (GG) events.
    return {"GR1", "GR2"} <= evt.groups


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_ics(
    events: list[CalendarEvent],
    profiles: list[Profile],
    output_dir: Path,
) -> dict[str, Path]:
    """
    Write one ICS file per profile into *output_dir*.

    Returns a mapping of ``profile.name → output_path``.
    """
    calendars: dict[str, Calendar] = {p.name: _new_calendar(p.name) for p in profiles}
    counts: dict[str, int] = {p.name: 0 for p in profiles}

    for evt in events:
        for profile in profiles:
            if _event_in_profile(evt, profile):
                calendars[profile.name].add_component(_build_ical_event(evt))
                counts[profile.name] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for profile in profiles:
        path = output_dir / f"calendar_{profile.name}.ics"
        path.write_bytes(calendars[profile.name].to_ical())
        logger.info("%s: %d events → %s", profile.name, counts[profile.name], path)
        paths[profile.name] = path

    return paths
