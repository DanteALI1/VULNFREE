"""HTTP helpers with timeout and limited retries."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


def request_with_retries(
    method: str,
    url: str,
    *,
    timeout: int = 30,
    max_attempts: int = 3,
    headers: dict | None = None,
    params: dict | None = None,
    verify: bool = True,
    stream: bool = False,
) -> requests.Response:
    """GET/POST with timeout, 429 exponential backoff, max 3 attempts."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(
                method,
                url,
                timeout=timeout,
                headers=headers or {},
                params=params,
                verify=verify,
                stream=stream,
            )
            if resp.status_code == 429:
                wait = 2**attempt
                logger.warning("HTTP 429 for %s, backoff %ss (attempt %s)", url, wait, attempt)
                time.sleep(wait)
                continue
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            wait = 2**attempt
            logger.warning("Request error %s: %s; retry in %ss", url, exc, wait)
            time.sleep(wait)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url}")


def get_json(url: str, **kwargs: Any) -> dict | list:
    resp = request_with_retries("GET", url, **kwargs)
    resp.raise_for_status()
    return resp.json()
