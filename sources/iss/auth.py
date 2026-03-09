"""
ISS-specific authentication wrapper.

Delegates to the shared UMA campus auth in sources.uma.auth.
Only this module knows the ISS course URL; callers in the ISS package
can import get_authenticated_session() without caring about the URL.
"""

import logging

import requests

from sources.uma.auth import get_authenticated_session as _get_authenticated_session

logger = logging.getLogger(__name__)

TARGET_URL = "https://informatica.cv.uma.es/course/view.php?id=5878"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_authenticated_session() -> requests.Session:
    """
    Return a :class:`requests.Session` authenticated against the UMA campus,
    using the ISS course URL to trigger and verify the SAML flow.
    """
    return _get_authenticated_session(TARGET_URL)
