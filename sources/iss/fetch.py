"""
Fetch the planning image from the UMA virtual campus course page.

Strategy:
  - Find a .no-overflow div whose text contains "PLANIFICACIÓN PROPUESTA".
  - Within it, grab the first <img> whose src contains "planning" (case-insensitive).
  - Download the image bytes via the authenticated session.
"""

import logging
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

from sources.iss.auth import TARGET_URL

logger = logging.getLogger(__name__)

IMG_OUT = Path(__file__).parent.parent.parent / "planning.png"


def _find_iss_planning_img_url(html: str, page_url: str) -> str:
    """
    ISS-specific: parse *html* from the ISS Moodle course page and return the
    absolute URL of the planning image (a .no-overflow div containing
    "PLANIFICACIÓN" with an <img src=*planning*>).

    Raises ValueError if the image cannot be located.
    """
    soup = BeautifulSoup(html, "lxml")

    for div in soup.find_all("div", class_="no-overflow"):
        # Check whether this div's direct text (ignoring child tags) contains
        # the section heading.  NavigableString iteration is the cleanest way.
        text = " ".join(s.strip() for s in div.strings if s.strip())
        if "PLANIFICACI" not in text.upper():  # covers Ó / O variants
            continue

        img: Tag | None = div.find(
            "img",
            src=re.compile(r"planning", re.IGNORECASE),
        )
        if img is None:
            continue

        src_attr = img.get("src")
        if not isinstance(src_attr, str):
            continue
        src: str = src_attr
        if src.startswith("http"):
            return src

        # Resolve relative URLs against the page base
        from urllib.parse import urljoin

        return urljoin(page_url, src)

    raise ValueError(
        "Could not find the planning image on the course page. The page structure may have changed."
    )


def fetch_planning_image(session: requests.Session) -> Path:
    """
    Download the planning image from the course page and save it to disk.

    Returns the :class:`~pathlib.Path` where the image was saved.
    """
    logger.info("Fetching course page: %s", TARGET_URL)
    resp = session.get(TARGET_URL, timeout=15)
    resp.raise_for_status()

    img_url = _find_iss_planning_img_url(resp.text, resp.url)
    logger.info("Found planning image: %s", img_url)

    logger.info("Downloading image …")
    img_resp = session.get(img_url, timeout=30)
    img_resp.raise_for_status()

    IMG_OUT.write_bytes(img_resp.content)
    logger.info("Image saved to %s (%d bytes)", IMG_OUT, len(img_resp.content))

    return IMG_OUT
