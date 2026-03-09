"""
Fetch the SAW planning PDF from the UMA virtual campus course page.

Strategy:
  - Load the SAW course page.
  - Find an <a> element that contains a <span class="instancename"> whose
    text starts with "Calendario" (case-insensitive).  The span text is stable;
    the href is not.
  - GET that href (Moodle resource redirect) to obtain the raw PDF bytes.
"""

import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

COURSE_URL = "https://informatica.cv.uma.es/course/view.php?id=5741"
PDF_OUT = Path(__file__).parent.parent.parent / "saw_planning.pdf"


def _find_calendario_href(html: str, page_url: str) -> str:
    """
    SAW-specific: scan *html* for an activity link whose span.instancename
    text starts with "Calendario" and return its href.

    Raises ValueError if the link is not found.
    """
    soup = BeautifulSoup(html, "lxml")

    for a in soup.find_all("a", class_="aalink"):
        span = a.find("span", class_="instancename")
        if span is None:
            continue
        # The span may contain a nested <span class="accesshide">,
        # so read only the direct text node (first NavigableString).
        visible_text = next((s.strip() for s in span.strings if s.strip()), "")
        if visible_text.lower().startswith("calendario"):
            href = a.get("href", "")
            if href:
                return str(href)

    raise ValueError(
        "Could not find a 'Calendario' activity link on the SAW course page. "
        "The page structure may have changed."
    )


def fetch_planning_pdf(session: requests.Session) -> Path:
    """
    Download the SAW planning PDF from the course page and save it to disk.

    Returns the :class:`~pathlib.Path` where the PDF was saved.
    """
    logger.info("Fetching SAW course page: %s", COURSE_URL)
    resp = session.get(COURSE_URL, timeout=15)
    resp.raise_for_status()

    resource_url = _find_calendario_href(resp.text, resp.url)
    logger.info("Found calendar resource link: %s", resource_url)

    # Moodle resource pages redirect (302) to the actual file.
    logger.info("Downloading PDF …")
    pdf_resp = session.get(resource_url, allow_redirects=True, timeout=30)
    pdf_resp.raise_for_status()

    content_type = pdf_resp.headers.get("Content-Type", "")
    if "pdf" not in content_type.lower():
        logger.warning("Unexpected Content-Type %r — proceeding anyway.", content_type)

    PDF_OUT.write_bytes(pdf_resp.content)
    logger.info("PDF saved to %s (%d bytes)", PDF_OUT, len(pdf_resp.content))

    return PDF_OUT
