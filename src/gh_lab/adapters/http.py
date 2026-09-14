"""Adapter for fetching JSON over HTTP.

Uses :mod:`urllib` from the standard library: the extension is run straight from
a checkout with nothing installed, so it cannot depend on third-party packages.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from gh_lab.adapters import AdapterError

TIMEOUT_SECONDS = 15

# Generous for a course configuration file, small enough that a wrong URL cannot
# stall the command by streaming something enormous.
MAX_BYTES = 1024 * 1024

ALLOWED_SCHEMES = ("http", "https")


def fetch_json(url: str) -> Any:
    """Fetch ``url`` and return the parsed JSON body.

    Args:
        url: An ``http`` or ``https`` URL.

    Raises:
        AdapterError: If the URL is unusable, unreachable, too large, or does
            not contain JSON.
    """
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        # urlopen would otherwise happily read file:// URLs.
        raise AdapterError(f"{url!r} is not an http or https URL")

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise AdapterError(f"{url} returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise AdapterError(f"could not reach {url}: {error}") from error

    if len(body) > MAX_BYTES:
        raise AdapterError(f"{url} returned more than {MAX_BYTES} bytes")

    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AdapterError(f"{url} did not return valid JSON") from error
