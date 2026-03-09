"""
Shared data models for all calendar sources and the exporter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class CalendarEvent:
    """A normalised calendar event produced by any CalendarSource."""

    subject: str
    date: date
    summary: str  # e.g. "[T] Ingeniería del Software Seguro"
    description: str  # topic / contenido
    location: str
    # Which groups should see this event, e.g. {"GR1"}, {"GR1", "GR2"}.
    # Use {"ALL"} for events that belong to every combination (e.g. TeamUp subjects).
    groups: set[str] = field(default_factory=set)
    # (hour, minute) of the event start.  None means an all-day event.
    time: tuple[int, int] | None = None
    # Duration in hours (may be fractional, e.g. 1.75 = 1h45m).
    # Ignored when time is None (all-day events).
    duration_hours: float = 1


@dataclass
class Profile:
    """
    A named combination of per-subject group choices used by the exporter to
    produce one personalised ICS file per student configuration.

    Example — a student in ISS GR2 and SAW GR1:
        Profile(
            name="ISS-GR2_SAW-GR1",
            groups={
                "Ingeniería del Software Seguro": "GR2",
                "Seguridad en Aplicaciones Web": "GR1",
            },
        )

    An event is included in this profile when:
      - ``"ALL" in event.groups``  (universal event, e.g. other TeamUp subjects), OR
      - The profile has a group entry for the event's subject AND that group is
        listed in the event's ``groups`` set.
    """

    name: str
    groups: dict[str, str]  # subject name → chosen group name
