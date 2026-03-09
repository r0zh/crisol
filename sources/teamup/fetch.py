"""
Download a TeamUp calendar ICS feed.
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

ICS_OUT = Path(__file__).parent.parent.parent / "teamup.ics"


def fetch_teamup_ics(url: str) -> Path:
    """
    Download the ICS feed from *url* and save it to disk.

    Returns the path to the saved file.
    """
    logger.info("Downloading TeamUp ICS from %s …", url)
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = resp.read()
    ICS_OUT.write_bytes(data)
    logger.info("TeamUp ICS saved to %s (%d bytes)", ICS_OUT, len(data))
    return ICS_OUT
