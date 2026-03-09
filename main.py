import itertools
import logging
from pathlib import Path

from export import export_ics
from models import Profile
from sources.aboc.source import ABOCSource
from sources.base import CalendarSource
from sources.iss.source import ISSSource
from sources.saw.source import SAWSource
from sources.teamup.source import TeamUpSource

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

TEAMUP_URL = "https://ics.teamup.com/feed/ksb252cpkbrhvb9zi8/14989481.ics"

# The four subjects with GR1/GR2 lab splits.
# Each subject key must match exactly what the source sets as CalendarEvent.subject.
_SUBJECTS: dict[str, str] = {
    "ISS": "Ingeniería del Software Seguro",
    "SAW": "Seguridad en Aplicaciones Web",
    "AC2": "Aprendizaje Computacional II",
    "BD": "Bases de Datos",
}

# Generate all 2⁴ = 16 group combinations.
PROFILES: list[Profile] = [
    Profile(
        name=f"ISS-{iss}_SAW-{saw}_AC2-{ac2}_BD-{bd}",
        groups={
            _SUBJECTS["ISS"]: iss,
            _SUBJECTS["SAW"]: saw,
            _SUBJECTS["AC2"]: ac2,
            _SUBJECTS["BD"]: bd,
        },
    )
    for iss, saw, ac2, bd in itertools.product(("GR1", "GR2"), repeat=4)
]


def main() -> None:
    # 1. Download TeamUp first — SAW borrows its time blocks from it.
    teamup = TeamUpSource(url=TEAMUP_URL)
    saw_blocks = teamup.get_time_blocks("Seguridad en Aplicaciones Web")

    # 2. Run the ISS OCR pipeline once; reuse the cached result for holidays.
    iss = ISSSource()
    iss.get_events()  # triggers OCR; result is cached internally
    iss_holidays = iss.get_holidays()

    sources: list[CalendarSource] = [
        iss,
        SAWSource(time_blocks=saw_blocks),
        ABOCSource(holidays=iss_holidays),
        teamup,
    ]

    all_events = [evt for src in sources for evt in src.get_events()]
    paths = export_ics(all_events, PROFILES, Path("calendars"))

    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
