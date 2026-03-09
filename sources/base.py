"""
Protocol that every calendar source must implement.

Adding a new source (PDF, image, scraper, …) means creating a class that
satisfies CalendarSource — no changes to existing code required.
"""

from __future__ import annotations

from typing import Protocol

from models import CalendarEvent


class CalendarSource(Protocol):
    """A source that can fetch raw data and return normalised CalendarEvents."""

    def get_events(self) -> list[CalendarEvent]:
        """Fetch and parse the raw data, returning a list of CalendarEvents."""
        ...
