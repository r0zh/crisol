"""
CalendarSource implementation for a TeamUp ICS feed.

Fetches all events from the feed, strips out subjects that are handled by
dedicated sources (ISS, SAW), and exposes a helper to extract per-date time
blocks for a given subject keyword (used by SAWSource to attach real times to
its PDF-parsed all-day events).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from models import CalendarEvent
from sources.teamup.fetch import fetch_teamup_ics
from sources.teamup.parse import get_time_blocks, parse_teamup_events

logger = logging.getLogger(__name__)

# Subjects managed by dedicated sources — their TeamUp entries are skipped so
# we do not create duplicates.  Matching is a case-insensitive prefix check
# against the cleaned SUMMARY (email suffix already stripped).
_DEFAULT_SKIP: set[str] = {
    # ISS — name may appear truncated/encoded in the ICS.
    "ingenier",
    # SAW
    "seguridad en aplicaciones web",
}


class TeamUpSource:
    """
    Sources events from a public TeamUp ICS feed.

    Args:
        url: Full URL to the TeamUp ICS feed.
        skip_subjects: Set of subject name prefixes (case-insensitive) to
            exclude from the output.  Defaults to ISS and SAW since those
            are covered by their own sources.
    """

    def __init__(
        self,
        url: str,
        skip_subjects: set[str] = _DEFAULT_SKIP,
        date_from: date | None = date(2026, 2, 1),
    ) -> None:
        self.url = url
        self.skip_subjects = skip_subjects
        self.date_from = date_from
        self._ics_path: Path | None = None

    def _ensure_downloaded(self) -> Path:
        if self._ics_path is None or not self._ics_path.exists():
            self._ics_path = fetch_teamup_ics(self.url)
        return self._ics_path

    def get_events(self) -> list[CalendarEvent]:
        """Download the ICS and return all non-skipped events."""
        return parse_teamup_events(
            self._ensure_downloaded(), self.skip_subjects, date_from=self.date_from
        )

    def get_time_blocks(self, subject_keyword: str) -> dict[date, tuple[tuple[int, int], int]]:
        """
        Return a ``date → ((hour, minute), duration_hours)`` mapping for events
        whose SUMMARY contains *subject_keyword*.

        Use this to enrich another source's all-day events with real times:

            blocks = teamup.get_time_blocks("Seguridad en Aplicaciones Web")
            saw_source = SAWSource(time_blocks=blocks)
        """
        return get_time_blocks(self._ensure_downloaded(), subject_keyword)
