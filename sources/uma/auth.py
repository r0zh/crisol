"""
SAML2 SSO authentication for the UMA virtual campus (Moodle via idp.uma.es).

This module is shared by all sources that live on informatica.cv.uma.es.
Each source passes its own course URL so the auth flow triggers the right
SAML redirect and the cookie-validity check hits the correct protected page.

Flow:
  1. GET course_url → campus redirects to idp.uma.es login page.
  2. POST credentials to the IdP action URL (with hidden SAML fields).
  3. IdP returns an HTML auto-submit form containing SAMLResponse.
  4. POST that form back to the SP (campus) → session cookie is set.
  5. Persist cookies to disk; reload on next run to skip login when still valid.
"""

import json
import logging
import os
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# One shared cookie jar for the entire UMA campus.
COOKIES_FILE = Path(__file__).parent.parent.parent / "cookies.json"

SESSION_COOKIE = "MoodleSession"


# ---------------------------------------------------------------------------
# Cookie persistence helpers
# ---------------------------------------------------------------------------


def _save_cookies(session: requests.Session) -> None:
    data = {c.name: c.value for c in session.cookies}
    COOKIES_FILE.write_text(json.dumps(data, indent=2))
    logger.debug("Cookies saved to %s", COOKIES_FILE)


def _load_cookies(session: requests.Session) -> bool:
    """Load cookies from disk into *session*. Returns True if file existed."""
    if not COOKIES_FILE.exists():
        return False
    data = json.loads(COOKIES_FILE.read_text())
    session.cookies.update(data)
    logger.debug("Cookies loaded from %s", COOKIES_FILE)
    return True


def _is_authenticated(session: requests.Session, course_url: str) -> bool:
    """
    Verify that *session* can access *course_url* without being redirected
    to the campus login page.
    """
    resp = session.get(course_url, allow_redirects=True, timeout=15)
    return resp.url.startswith("https://informatica.cv.uma.es") and "/login/" not in resp.url


# ---------------------------------------------------------------------------
# SAML login
# ---------------------------------------------------------------------------


def _do_saml_login(
    session: requests.Session, username: str, password: str, course_url: str
) -> None:
    """
    Perform the full SAML2 redirect-chain login starting from *course_url*.
    Raises RuntimeError on failure.
    """
    logger.info("Starting SAML2 login for %s …", username)

    # --- Step 1: GET course URL to trigger the SAML redirect to the IdP ---
    resp = session.get(course_url, allow_redirects=True, timeout=15)
    resp.raise_for_status()

    if resp.url.startswith("https://informatica.cv.uma.es") and "/login/" not in resp.url:
        logger.info("Already authenticated (no redirect to IdP).")
        return

    soup = BeautifulSoup(resp.text, "lxml")
    form = soup.find("form", id="formulario1") or soup.find("form")
    if form is None:
        raise RuntimeError("Could not find the IdP login form in the response.")

    action = str(form.get("action", resp.url))

    payload: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        value = inp.get("value", "")
        if name:
            payload[str(name)] = str(value) if value else ""

    payload["adAS_username"] = username
    payload["adAS_password"] = password

    # --- Step 2: POST credentials to the IdP ---
    logger.info("Posting credentials to %s", action)
    resp2 = session.post(action, data=payload, allow_redirects=True, timeout=15)
    resp2.raise_for_status()

    # --- Step 3: Handle SAMLResponse auto-submit form ---
    soup2 = BeautifulSoup(resp2.text, "lxml")
    saml_form = soup2.find("form")

    if saml_form is None:
        error = soup2.find(id="login_ko_label") or soup2.find(class_="error")
        msg = error.get_text(strip=True) if error else "Unknown error"
        raise RuntimeError(f"Login failed — IdP returned no SAMLResponse form. Error: {msg}")

    saml_action = str(saml_form.get("action", ""))
    saml_payload: dict[str, str] = {}
    for inp in saml_form.find_all("input"):
        name = inp.get("name")
        value = inp.get("value", "")
        if name:
            saml_payload[str(name)] = str(value) if value else ""

    if "SAMLResponse" not in saml_payload:
        raise RuntimeError("SAMLResponse hidden field not found — login may have failed.")

    # --- Step 4: Follow the SAML chain (may be multiple SP hops) ---
    current_action = saml_action
    current_payload = saml_payload

    for hop in range(1, 6):
        logger.info("SAML hop %d: posting to %s", hop, current_action)
        resp = session.post(current_action, data=current_payload, allow_redirects=True, timeout=15)
        resp.raise_for_status()

        if resp.url.startswith("https://informatica.cv.uma.es") and "/login/" not in resp.url:
            logger.info("Login successful after %d SAML hop(s).", hop)
            return

        soup_hop = BeautifulSoup(resp.text, "lxml")
        next_form = soup_hop.find("form")
        if next_form is None:
            raise RuntimeError(
                f"SAML hop {hop}: no further form found, but not on campus URL. "
                f"Landed on: {resp.url}"
            )

        next_action = str(next_form.get("action", ""))
        next_payload: dict[str, str] = {}
        for inp in next_form.find_all("input"):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                next_payload[str(name)] = str(value) if value else ""

        if not next_action:
            raise RuntimeError(
                f"SAML hop {hop}: form has no action attribute. Landed on: {resp.url}"
            )

        current_action = next_action
        current_payload = next_payload

    raise RuntimeError("SAML chain exceeded maximum hop limit without reaching the campus.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_authenticated_session(course_url: str) -> requests.Session:
    """
    Return a :class:`requests.Session` authenticated against the UMA virtual
    campus.  Reuses cached cookies when possible; falls back to a full SAML
    login against *course_url* otherwise.

    Credentials are read from the environment (or a .env file):
      UMA_USERNAME, UMA_PASSWORD
    """
    username = os.environ.get("UMA_USERNAME")
    password = os.environ.get("UMA_PASSWORD")

    if not username or not password:
        raise OSError("Missing credentials. Set UMA_USERNAME and UMA_PASSWORD in a .env file.")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }
    )

    if _load_cookies(session) and _is_authenticated(session, course_url):
        logger.info("Reusing saved session cookies.")
        return session

    session.cookies.clear()
    _do_saml_login(session, username, password, course_url)
    _save_cookies(session)

    return session
