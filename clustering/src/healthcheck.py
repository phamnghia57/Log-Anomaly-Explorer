"""Best-effort Healthchecks.io signals; ping URLs are secrets."""
import logging
import os
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger("clustering.healthcheck")


def ping(*, failed=False):
    url = os.environ.get("HEALTHCHECK_PING_URL", "").strip()
    if not url:
        return
    try:
        if failed:
            parts = urlsplit(url)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + "/fail", parts.query, parts.fragment))
        response = httpx.get(url, timeout=2.0)
        response.raise_for_status()
    except Exception:
        # Exceptions and request URLs can contain the private ping token.
        logger.warning("Healthcheck signal failed")
