"""HTTP retry utilities for external API calls.

Provides retry logic with exponential backoff for HTTP requests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


async def http_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retryable_status_codes: set[int] | None = None,
    **kwargs,
) -> httpx.Response:
    """Make HTTP request with retry logic and exponential backoff.

    Args:
        client: httpx AsyncClient instance
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay between retries
        backoff_factor: Multiplier for exponential backoff
        retryable_status_codes: Set of HTTP status codes that should trigger retry
        **kwargs: Additional arguments passed to client.request()

    Returns:
        httpx.Response object

    Raises:
        httpx.HTTPStatusError: If request fails after all retries
        httpx.RequestError: If request fails due to network error
    """
    if retryable_status_codes is None:
        retryable_status_codes = {429, 500, 502, 503, 504}

    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            if attempt > 0:
                logger.info(
                    "HTTP request succeeded on retry %d/%d: %s %s",
                    attempt + 1,
                    max_retries + 1,
                    method,
                    url,
                )
            return response

        except httpx.HTTPStatusError as e:
            last_exception = e
            status_code = e.response.status_code

            # Don't retry on client errors (4xx) except rate limits
            if 400 <= status_code < 500 and status_code not in retryable_status_codes:
                logger.error(
                    "HTTP client error (non-retryable): %d %s %s",
                    status_code,
                    method,
                    url,
                )
                raise

            # Retry on server errors or rate limits
            if status_code in retryable_status_codes and attempt < max_retries:
                delay = min(initial_delay * (backoff_factor**attempt), max_delay)
                logger.warning(
                    "HTTP %d error, retrying (%d/%d) in %.2fs: %s %s",
                    status_code,
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    method,
                    url,
                )
                await asyncio.sleep(delay)
                continue

            # All retries exhausted
            logger.error(
                "HTTP request failed after %d attempts: %d %s %s",
                max_retries + 1,
                status_code,
                method,
                url,
            )
            raise

        except (httpx.RequestError, httpx.TimeoutException, asyncio.TimeoutError) as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(initial_delay * (backoff_factor**attempt), max_delay)
                logger.warning(
                    "Network error, retrying (%d/%d) in %.2fs: %s %s - %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    method,
                    url,
                    str(e)[:100],
                )
                await asyncio.sleep(delay)
                continue

            # All retries exhausted
            logger.error(
                "Network error after %d attempts: %s %s - %s",
                max_retries + 1,
                method,
                url,
                str(e),
            )
            raise

        except Exception as e:
            # Unexpected errors - don't retry
            logger.error("Unexpected error in HTTP request: %s %s - %s", method, url, str(e))
            raise

    # Should never reach here, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("HTTP request failed for unknown reason")

