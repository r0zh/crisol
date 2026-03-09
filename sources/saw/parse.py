"""
Parse the SAW planning PDF and convert its tables to CalendarEvents.

PDF table structure
-------------------
Table 1  –  weekly schedule
  Columns: Semana | Día | Fecha | Aula | Grupo

  - Semana:  week label ("S1", "S4\\nHACKER\\nWEEK", …); None for continuation rows.
  - Día:     day abbreviation (L, M, J).
  - Fecha:   date string "D/M/YYYY" (may omit century: "D/M/YY").
  - Aula:    classroom ("3.0.9", "L10", "L1", …) or empty → no class / holiday.
  - Grupo:   "GG" (both groups), "GR1", "GR2", or empty.

Table 2  –  partial exams
  Columns: exam_name | date_str
  Rows: "Parcial B1" … "Parcial B3"

Group mapping
-------------
  GG   → {GR1, GR2}
  GR1  → {GR1}
  GR2  → {GR2}
  ""   → skip (holiday or unscheduled slot)

Session type inference (from Aula)
------------------------------------
  "3.0.9"              → lecture   → "[T]"
  "L10" / "L1" / L*   → lab       → "[P]"
  (exam rows)          → "[E]"
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import pdfplumber

from models import CalendarEvent

logger = logging.getLogger(__name__)

SUBJECT = "Seguridad en Aplicaciones Web"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(fecha: str) -> date | None:
    """Parse 'D/M/YYYY' or 'D/M/YY' → date.  Returns None on failure."""
    fecha = fecha.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", fecha)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _groups_from_grupo(grupo: str | None) -> set[str]:
    """Map the PDF Grupo cell to a group set."""
    g = (grupo or "").strip().upper()
    if g == "GG":
        return {"GR1", "GR2"}
    if g in ("GR1", "GR2"):
        return {g}
    return set()


def _event_tag(aula: str) -> str:
    """Infer the event type tag from the classroom."""
    a = (aula or "").strip()
    if re.match(r"^[Ll]\d+", a):  # L10, L1, Lab*, …
        return "[P]"
    return "[T]"


def _semana_note(semana: str | None) -> str:
    """
    Extract the optional week theme from a Semana cell.

    "S4\\nHACKER\\nWEEK" → "HACKER WEEK"
    "S1"                  → ""
    """
    if not semana:
        return ""
    # The first line is always the week number; the rest is the note.
    parts = [p.strip() for p in semana.splitlines()]
    note = " ".join(parts[1:]).strip()
    return note


# ---------------------------------------------------------------------------
# Table parsers
# ---------------------------------------------------------------------------


def _parse_schedule_table(
    table: list[list[str | None]],
) -> list[CalendarEvent]:
    """Convert the main schedule table (Table 1) into CalendarEvents."""
    events: list[CalendarEvent] = []
    last_semana: str | None = None

    for row in table[1:]:  # skip header
        semana_raw, _dia, fecha_raw, aula_raw, grupo_raw = (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
        )

        # Track the last seen Semana label (continuation rows have None).
        if semana_raw is not None:
            last_semana = semana_raw

        aula = (aula_raw or "").strip()
        grupo = (grupo_raw or "").strip()

        # Rows without an Aula or Grupo are holidays / unscheduled slots.
        if not aula or not grupo:
            continue

        groups = _groups_from_grupo(grupo)
        if not groups:
            continue

        dt = _parse_date(fecha_raw or "")
        if dt is None:
            logger.warning("Could not parse date %r — skipping row.", fecha_raw)
            continue

        tag = _event_tag(aula)
        note = _semana_note(last_semana)

        events.append(
            CalendarEvent(
                subject=SUBJECT,
                date=dt,
                summary=f"{tag} {SUBJECT}",
                description=note,
                location=aula,
                groups=groups,
            )
        )

    return events


def _parse_exam_table(
    table: list[list[str | None]],
) -> list[CalendarEvent]:
    """Convert the exam table (Table 2) into CalendarEvents."""
    events: list[CalendarEvent] = []

    for row in table:
        if len(row) < 2:
            continue
        name_raw, fecha_raw = row[0], row[1]
        name = (name_raw or "").strip()
        if not name:
            continue

        dt = _parse_date(fecha_raw or "")
        if dt is None:
            logger.warning("Could not parse exam date %r for %r — skipping.", fecha_raw, name)
            continue

        events.append(
            CalendarEvent(
                subject=SUBJECT,
                date=dt,
                summary=f"[E] {SUBJECT}",
                description=name,
                location="3.0.9",
                groups={"GR1", "GR2"},
            )
        )

    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_planning_pdf(pdf_path: Path) -> list[CalendarEvent]:
    """
    Extract CalendarEvents from the SAW planning PDF at *pdf_path*.

    Events have no time set (``time=None``, i.e. all-day) because the PDF
    does not include class hours.  Set a specific start time by passing
    ``start_time`` to :class:`~sources.saw.source.SAWSource`.

    Post-processing: if a date has both a ``[T]`` and an ``[E]`` event with
    overlapping groups, the ``[T]`` event is dropped (exam supersedes lecture).
    """
    logger.info("Parsing SAW planning PDF: %s", pdf_path)
    events: list[CalendarEvent] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            logger.debug("Page %d: found %d table(s).", page_num, len(tables))

            for table in tables:
                if not table:
                    continue
                header = [str(c or "").strip() for c in table[0]]

                if "Fecha" in header and "Aula" in header:
                    # Main schedule table
                    events.extend(_parse_schedule_table(table))
                elif len(table[0]) == 2 and re.search(
                    r"parcial", str(table[0][0] or ""), re.IGNORECASE
                ):
                    # Exam table (first cell contains "Parcial …")
                    events.extend(_parse_exam_table(table))
                else:
                    logger.debug("Skipping unrecognised table (header=%r).", header)

    # Drop [T] events on dates that already have a [E] with overlapping groups.
    exam_dates: dict[date, set[str]] = {}
    for evt in events:
        if evt.summary.startswith("[E]"):
            exam_dates.setdefault(evt.date, set()).update(evt.groups)

    if exam_dates:
        before = len(events)
        events = [
            evt
            for evt in events
            if not (
                evt.summary.startswith("[T]")
                and evt.date in exam_dates
                and evt.groups & exam_dates[evt.date]
            )
        ]
        dropped = before - len(events)
        if dropped:
            logger.info(
                "Dropped %d [T] event(s) that overlap with [E] on the same date.",
                dropped,
            )

    logger.info("Parsed %d SAW events from PDF.", len(events))
    return events
