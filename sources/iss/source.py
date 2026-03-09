"""
CalendarSource implementation for Ingeniería del Software Seguro (UMA Moodle).

Fetches the planning image via an authenticated Moodle session, runs OCR on it,
and returns normalised CalendarEvent objects ready for export.
"""

from __future__ import annotations

import logging
from datetime import date

from models import CalendarEvent
from sources.iss.auth import get_authenticated_session
from sources.iss.fetch import fetch_planning_image
from sources.iss.parse import run_ocr

logger = logging.getLogger(__name__)


class ISSSource:
    """
    Calendar source for Ingeniería del Software Seguro.

    Satisfies the CalendarSource protocol — plug it into the main pipeline
    alongside any other CalendarSource implementation.

    The OCR pipeline is run at most once: the first call to either
    ``get_events()`` or ``get_holidays()`` fetches and parses the image, and
    the result is cached for subsequent calls.
    """

    def __init__(self) -> None:
        self._events: list[CalendarEvent] | None = None
        self._holidays: set[date] | None = None

    def _ensure_parsed(self) -> None:
        if self._events is None:
            session = get_authenticated_session()
            img_path = fetch_planning_image(session)
            self._events, self._holidays = run_ocr(img_path)

    def get_events(self) -> list[CalendarEvent]:
        """Authenticate, download the planning image, OCR it, and return events."""
        self._ensure_parsed()
        assert self._events is not None
        return self._events

    def get_holidays(self) -> set[date]:
        """Return the set of holiday dates detected in the ISS planning image."""
        self._ensure_parsed()
        assert self._holidays is not None
        return self._holidays
