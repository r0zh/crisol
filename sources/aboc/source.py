"""
Hardcoded weekly schedule for Algoritmos de Búsqueda y Optimización Computacional.

No official planning document exists for this subject; the timetable is fixed:

    Monday    (L): 10:45 – 12:45  (2h)
    Wednesday (X):  8:45 – 10:45  (2h)

    Range: 2026-02-18 → 2026-06-08 (inclusive)

All sessions are whole-class (GG), so events carry groups={"GR1", "GR2"} and
appear in every export profile.

An optional set of *holidays* can be supplied (e.g. from ISSSource) so that
sessions falling on public holidays or academic breaks are automatically
excluded rather than hard-coded.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from models import CalendarEvent

logger = logging.getLogger(__name__)

SUBJECT = "Algoritmos de Búsqueda y Optimización Computacional"

_START = date(2026, 2, 18)
_END = date(2026, 6, 8)

# weekday → (hour, minute, duration_hours)
# Monday=0, Wednesday=2
# 10:45–12:45 and 8:45–10:45 are both 2h
_SCHEDULE: dict[int, tuple[int, int, float]] = {
    0: (10, 45, 2.0),  # Monday    10:45 – 12:45
    2: (8, 45, 2.0),  # Wednesday  8:45 – 10:45
}


class ABOCSource:
    """
    Generates hardcoded weekly events for ABOC between *_START* and *_END*.

    Since there is no GR1/GR2 lab split for this subject, every event targets
    both groups (groups={"GR1", "GR2"}) and is therefore included in all
    export profiles automatically.

    Parameters
    ----------
    holidays:
        An optional set of dates to skip.  Any ABOC session whose date appears
        in this set is omitted from the output.  Pass ``ISSSource().get_holidays()``
        to automatically respect the holiday blocks detected in the ISS planning
        image (Día de Andalucía, Semana Santa, Día del Trabajador, etc.).
    """

    def __init__(self, holidays: set[date] | None = None) -> None:
        self._holidays: set[date] = holidays if holidays is not None else set()

    def get_events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        current = _START
        while current <= _END:
            if current.weekday() in _SCHEDULE:
                if current in self._holidays:
                    logger.debug("Skipping ABOC session on holiday %s.", current)
                else:
                    hour, minute, duration = _SCHEDULE[current.weekday()]
                    events.append(
                        CalendarEvent(
                            subject=SUBJECT,
                            date=current,
                            summary=f"[T] {SUBJECT}",
                            description="",
                            location="",
                            groups={"GR1", "GR2"},
                            time=(hour, minute),
                            duration_hours=duration,
                        )
                    )
            current += timedelta(days=1)

        logger.info(
            "Generated %d ABOC events (%s → %s), %d holiday dates skipped.",
            len(events),
            _START,
            _END,
            len(self._holidays),
        )
        return events
