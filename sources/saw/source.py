"""
CalendarSource implementation for Seguridad en Aplicaciones Web (SAW).

Fetches the planning PDF via an authenticated Moodle session, parses it,
and returns normalised CalendarEvent objects ready for export.

Real class times are not in the PDF.  Pass a ``time_blocks`` dict (typically
obtained from TeamUpSource.get_time_blocks()) to attach real DTSTART times to
each event based on its date.  Dates with no entry in the dict remain all-day.
"""

from __future__ import annotations

import logging
from datetime import date

from models import CalendarEvent
from sources.saw.fetch import COURSE_URL, fetch_planning_pdf
from sources.saw.parse import parse_planning_pdf
from sources.uma.auth import get_authenticated_session

logger = logging.getLogger(__name__)


class SAWSource:
    """
    Calendar source for Seguridad en Aplicaciones Web.

    Args:
        time_blocks: Mapping of ``date → ((hour, minute), duration_hours)``
            used to attach real start times to each event.  Obtain this from
            ``TeamUpSource.get_time_blocks("Seguridad en Aplicaciones Web")``.
            Dates absent from the dict emit all-day events.
    """

    def __init__(
        self,
        time_blocks: dict[date, tuple[tuple[int, int], int]] | None = None,
    ) -> None:
        self.time_blocks = time_blocks or {}

    def get_events(self) -> list[CalendarEvent]:
        """Authenticate, download the planning PDF, parse it, and return events."""
        session = get_authenticated_session(COURSE_URL)
        pdf_path = fetch_planning_pdf(session)
        events = parse_planning_pdf(pdf_path)

        for evt in events:
            block = self.time_blocks.get(evt.date)
            if block is not None:
                evt.time, evt.duration_hours = block

        enriched = sum(1 for e in events if e.time is not None)
        logger.info(
            "SAW: %d/%d events enriched with time blocks from TeamUp.",
            enriched,
            len(events),
        )
        return events
