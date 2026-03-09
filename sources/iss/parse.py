"""
OCR-parse the ISS planning image and convert rows to CalendarEvents.

Pipeline
--------
1. Run PaddleOCR on the image to get (bounding_box, text, confidence) tuples.
2. Cluster results into rows by y-centroid proximity.
3. Within each row, sort cells left-to-right and map them to the known
   column schema: S | Dia | Fecha | Hora | T | GR1 | GR2 | E | Tipo | Contenido
4. Convert each data row to a CalendarEvent, applying ISS-specific group rules:
     - T  == "2"          → both GR1 and GR2 (theory session)
     - GR1 == "2"         → GR1 only
     - GR2 == "2"         → GR2 only
     - E  != ""           → both GR1 and GR2 (evaluation)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path

from paddleocr import PaddleOCR

from models import CalendarEvent

# Suppress the model-hoster connectivity check (not needed when models are cached)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

logger = logging.getLogger(__name__)

SUBJECT = "Ingeniería del Software Seguro"
SCHEDULE_YEAR = 2026

# Column names in left-to-right order as they appear in the image.
COLUMNS = ["S", "Dia", "Fecha", "Hora", "T", "GR1", "GR2", "E", "Tipo", "Contenido"]

# Vertical tolerance (pixels) for grouping text blobs into the same row.
ROW_TOLERANCE = 15

# Spanish month abbreviations → month number
_MONTHS: dict[str, int] = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}

# Prefixes OCR may leave in Tipo when Contenido is empty (e.g. "Práctica GR1 SAST")
_TIPO_PREFIXES = re.compile(
    r"^(pr[aá]ctica\s+gr[12]\s*(y\s*gr[12])?\s*|teor[ií]a\s*|evaluaci[oó]n\s*)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# OCR geometry helpers
# ---------------------------------------------------------------------------


def _y_center(box: list) -> float:
    """Return the vertical centre of a bounding box (list of 4 [x,y] points)."""
    ys = [pt[1] for pt in box]
    return (min(ys) + max(ys)) / 2


def _x_center(box: list) -> float:
    """Return the horizontal centre of a bounding box."""
    xs = [pt[0] for pt in box]
    return (min(xs) + max(xs)) / 2


def _x_left(box: list) -> float:
    return min(pt[0] for pt in box)


def _x_right(box: list) -> float:
    return max(pt[0] for pt in box)


def _group_into_rows(
    results: list[tuple[list, str, float]],
    tolerance: int = ROW_TOLERANCE,
) -> list[list[tuple[list, str, float]]]:
    """
    Group OCR results into rows. Items whose y-centres are within *tolerance*
    pixels of each other belong to the same row.

    Returns a list of rows, each sorted left-to-right by x-centre.
    """
    sorted_items = sorted(results, key=lambda r: _y_center(r[0]))
    rows: list[list[tuple[list, str, float]]] = []
    current_row: list[tuple[list, str, float]] = []
    last_y: float | None = None

    for item in sorted_items:
        y = _y_center(item[0])
        if last_y is None or abs(y - last_y) <= tolerance:
            current_row.append(item)
            # Running average lets the row absorb slightly drifting text.
            last_y = y if last_y is None else (last_y + y) / 2
        else:
            if current_row:
                rows.append(sorted(current_row, key=lambda r: _x_center(r[0])))
            current_row = [item]
            last_y = y

    if current_row:
        rows.append(sorted(current_row, key=lambda r: _x_center(r[0])))

    return rows


def _assign_columns(
    row_items: list[tuple[list, str, float]],
    col_boundaries: list[float],
) -> dict[str, str]:
    """
    Map each cell in a row to a column name using pre-computed x-boundaries.

    *col_boundaries* is a list of N-1 x-values that split the image into N
    column regions (one per entry in COLUMNS).
    """
    record: dict[str, str] = {col: "" for col in COLUMNS}
    for box, text, _ in row_items:
        x = _x_center(box)
        col_idx = 0
        for boundary in col_boundaries:
            if x > boundary:
                col_idx += 1
            else:
                break
        col_idx = min(col_idx, len(COLUMNS) - 1)
        col_name = COLUMNS[col_idx]
        # Append in case multiple OCR blobs land in the same cell.
        record[col_name] = (record[col_name] + " " + text).strip()
    return record


def _infer_column_boundaries(
    header_row: list[tuple[list, str, float]],
) -> list[float]:
    """
    Derive column split-points from the header row.

    Uses the midpoint of the gap between adjacent header labels rather than
    centre-to-centre midpoints, yielding tighter boundaries for narrow columns.
    """
    sorted_items = sorted(header_row, key=lambda r: _x_center(r[0]))
    boundaries: list[float] = []
    for i in range(len(sorted_items) - 1):
        right_of_left = _x_right(sorted_items[i][0])
        left_of_right = _x_left(sorted_items[i + 1][0])
        boundaries.append((right_of_left + left_of_right) / 2)
    return boundaries


# ---------------------------------------------------------------------------
# ISS-specific row → CalendarEvent conversion
# ---------------------------------------------------------------------------


def _parse_date(fecha: str) -> date | None:
    """Parse '18 feb.' → date(2026, 2, 18). Returns None on failure."""
    fecha = fecha.strip().rstrip(".")
    m = re.match(r"(\d{1,2})\s*([a-záéíóú]{3})", fecha, re.IGNORECASE)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    return date(SCHEDULE_YEAR, month, day)


def _parse_time(hora: str) -> tuple[int, int] | None:
    """Parse '10:45' → (10, 45). Returns None on failure."""
    m = re.match(r"(\d{1,2}):(\d{2})", hora.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _duration_hours(row: dict[str, str]) -> int:
    """Return event duration in hours from whichever scheduling column is set."""
    for col in ("T", "GR1", "GR2", "E"):
        val = row.get(col, "").strip()
        if val.isdigit():
            return int(val)
    return 1  # fallback


def _event_tag(tipo: str) -> str:
    """Return [E], [T] or [P] based on the session type string."""
    t = tipo.lower()
    if "evaluac" in t or "examen" in t:
        return "[E]"
    if "teor" in t:
        return "[T]"
    if "práctica" in t or "practica" in t:
        return "[P]"
    return "[?]"


def _location(tipo: str) -> str:
    """Return the classroom based on session type."""
    t = tipo.lower()
    if "práctica" in t or "practica" in t:
        return "Laboratorio LCC"
    return "3.0.9"


def _description(row: dict[str, str]) -> str:
    """
    Return the event description.
    Prefer Contenido; when empty, strip the session-type prefix from Tipo
    to surface just the topic (e.g. "Práctica GR1 SAST" → "SAST").
    """
    contenido = row.get("Contenido", "").strip()
    if contenido:
        return contenido
    tipo = row.get("Tipo", "").strip()
    return _TIPO_PREFIXES.sub("", tipo).strip()


def _summary(row: dict[str, str]) -> str:
    tipo = row.get("Tipo", "").strip()
    return f"{_event_tag(tipo)} {SUBJECT}"


def _sanity_check(row: dict[str, str]) -> None:
    tipo = row.get("Tipo", "")
    fecha = row.get("Fecha", "")
    if row.get("T", "").strip() == "2" and "teor" not in tipo.lower():
        logger.warning("Sanity: T=2 but 'Teoría' not in Tipo=%r (Fecha=%s)", tipo, fecha)
    if row.get("GR1", "").strip() == "2" and "gr1" not in tipo.lower():
        logger.warning("Sanity: GR1=2 but 'GR1' not in Tipo=%r (Fecha=%s)", tipo, fecha)
    if row.get("GR2", "").strip() == "2" and "gr2" not in tipo.lower():
        logger.warning("Sanity: GR2=2 but 'GR2' not in Tipo=%r (Fecha=%s)", tipo, fecha)


def _row_to_event(row: dict[str, str]) -> CalendarEvent | None:
    """
    Convert an ISS table row to a CalendarEvent, or None if it should be skipped.

    Group assignment rules:
      T == "2"           → GR1 + GR2 (theory)
      GR1 == "2"         → GR1 only
      GR2 == "2"         → GR2 only
      E != ""            → GR1 + GR2 (evaluation)
    """
    t = row.get("T", "").strip()
    gr1 = row.get("GR1", "").strip()
    gr2 = row.get("GR2", "").strip()
    e = row.get("E", "").strip()

    in_gr1 = t == "2" or gr1 == "2" or e != ""
    in_gr2 = t == "2" or gr2 == "2" or e != ""

    if not in_gr1 and not in_gr2:
        return None

    dt = _parse_date(row.get("Fecha", ""))
    if dt is None:
        logger.warning("Could not parse date %r — skipping row.", row.get("Fecha"))
        return None

    hora = _parse_time(row.get("Hora", ""))
    if hora is None:
        logger.warning(
            "Could not parse time %r for %s — skipping row.",
            row.get("Hora"),
            row.get("Fecha"),
        )
        return None

    _sanity_check(row)

    groups: set[str] = set()
    if in_gr1:
        groups.add("GR1")
    if in_gr2:
        groups.add("GR2")

    tipo = row.get("Tipo", "").strip()
    return CalendarEvent(
        subject=SUBJECT,
        date=dt,
        time=hora,
        duration_hours=_duration_hours(row),
        summary=_summary(row),
        description=_description(row),
        location=_location(tipo),
        groups=groups,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_ocr(image_path: Path) -> tuple[list[CalendarEvent], set[date]]:
    """
    Run PaddleOCR on *image_path* and return a tuple of
    ``(events, holiday_dates)``.

    *holiday_dates* is the set of every calendar day that falls within a
    holiday block detected in the ISS planning image.  Single-day holidays
    (e.g. Día de Andalucía, Día del Trabajador) contribute exactly one date;
    multi-day blocks (e.g. Semana Santa) are expanded: any gap of more than
    7 days between consecutive ISS session dates is treated as a holiday range
    and every day in the gap is included.
    """
    logger.info("Running PaddleOCR on %s …", image_path)
    ocr = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )
    result = ocr.predict(str(image_path))

    items: list[tuple[list, str, float]] = []
    for res in result:
        polys = res["rec_polys"]  # numpy array (N, 4, 2)
        texts = res["rec_texts"]  # list[str]
        scores = res["rec_scores"]  # array (N,)
        for poly, text, score in zip(polys, texts, scores, strict=True):
            items.append((poly.tolist(), text, float(score)))

    if not items:
        raise ValueError("PaddleOCR returned no results for the image.")
    logger.info("OCR produced %d text blobs.", len(items))

    rows = _group_into_rows(items)
    logger.info("Grouped into %d rows.", len(rows))

    # Identify the header row by looking for known column-name tokens.
    header_row: list[tuple[list, str, float]] | None = None
    for row in rows:
        texts_set = {item[1].strip().upper() for item in row}
        if {"S", "DIA", "TIPO"}.issubset(texts_set) or len(
            texts_set & {"HORA", "DIA", "FECHA"}
        ) >= 2:
            header_row = row
            break

    if header_row is None:
        logger.warning("Could not identify header row; falling back to equal-width columns.")
        img_width = max(_x_center(it[0]) for row in rows for it in row) + 50
        step = img_width / len(COLUMNS)
        col_boundaries = [step * i for i in range(1, len(COLUMNS))]
    else:
        col_boundaries = _infer_column_boundaries(header_row)

    events: list[CalendarEvent] = []
    holiday_markers: list[date] = []
    skipped = 0
    for row in rows:
        if row is header_row:
            continue
        record = _assign_columns(row, col_boundaries)
        non_empty = sum(1 for v in record.values() if v)
        if non_empty < 2:
            continue  # separator or near-empty row
        event = _row_to_event(record)
        if event is None:
            skipped += 1
            # If the row carries a parseable date but no session markers it is
            # a holiday announcement row (e.g. "Día de Andalucía", "Semana Santa").
            dt = _parse_date(record.get("Fecha", ""))
            if dt is not None:
                holiday_markers.append(dt)
        else:
            events.append(event)

    # Build the full set of holiday dates.
    # For each holiday marker, check whether the next ISS session date is more
    # than 7 days away.  If so, the marker is the start of a multi-day block
    # (like Semana Santa) and every day up to (but not including) the next
    # session is a holiday.  Otherwise only the marker day itself is a holiday.
    event_dates = sorted({e.date for e in events})
    holidays: set[date] = set()
    for marker in holiday_markers:
        future_dates = [d for d in event_dates if d > marker]
        if future_dates and (future_dates[0] - marker).days > 7:
            # Multi-day holiday block — expand the full range.
            current = marker
            while current < future_dates[0]:
                holidays.add(current)
                current += timedelta(days=1)
        else:
            holidays.add(marker)

    logger.info(
        "Parsed %d events (%d rows skipped), %d holiday dates detected.",
        len(events),
        skipped,
        len(holidays),
    )
    return events, holidays
