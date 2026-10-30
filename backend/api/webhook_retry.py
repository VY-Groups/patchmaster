"""Webhook delivery with retry logic and exponential backoff."""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


# Retry configuration
MAX_RETRIES = 5
RETRY_DELAYS = [5, 20, 60, 300]  # 5s, 20s, 60s, 5min - last is max wait
MAX_RETRY_DELAY = 300  # 5 minutes max


class WebhookDeliveryError(Exception):
    """Raised when webhook delivery fails after all retries."""

    def __init__(self, message: str, attempts: int, last_error: Optional[str] = None):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class WebhookRetryConfig:
    """Configuration for webhook retry behavior."""

    def __init__(
        self,
        max_retries: int = MAX_RETRIES,
        retry_delays: list = None,
        timeout: float = 30.0,
    ):
        self.max_retries = max_retries
        self.retry_delays = retry_delays or RETRY_DELAYS
        self.timeout = timeout


async def deliver_with_retry(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    config: Optional[WebhookRetryConfig] = None,
) -> tuple[bool, int, list[Dict[str, Any]]]:
    """
    Deliver webhook with exponential backoff retry.

    Args:
        url: The webhook URL to send to
        payload: The JSON payload to send
        headers: Optional HTTP headers
        config: Retry configuration

    Returns:
        Tuple of (success, final_status_code, attempts_log)
    """
    if config is None:
        config = WebhookRetryConfig()

    attempts_log = []
    headers = headers or {"Content-Type": "application/json"}

    for attempt in range(config.max_retries):
        attempt_log = {
            "attempt": attempt + 1,
            "timestamp": datetime.utcnow().isoformat(),
            "url": url,
        }

        try:
            async with httpx.AsyncClient(timeout=config.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                attempt_log["status_code"] = response.status_code

                if response.status_code < 400:
                    # Success
                    attempt_log["success"] = True
                    attempts_log.append(attempt_log)
                    logger.info(
                        f"Webhook delivered successfully to {url} "
                        f"on attempt {attempt + 1}"
                    )
                    return True, response.status_code, attempts_log

                # Non-success status code
                attempt_log["success"] = False
                attempt_log["error"] = (
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                attempts_log.append(attempt_log)
                logger.warning(
                    f"Webhook delivery to {url} failed with HTTP {response.status_code} "
                    f"on attempt {attempt + 1}: {response.text[:200]}"
                )

        except httpx.TimeoutException as e:
            attempt_log["success"] = False
            attempt_log["error"] = f"Timeout: {str(e)}"
            attempts_log.append(attempt_log)
            logger.warning(
                f"Webhook delivery to {url} timed out on attempt {attempt + 1}"
            )

        except httpx.RequestError as e:
            attempt_log["success"] = False
            attempt_log["error"] = f"Request error: {str(e)}"
            attempts_log.append(attempt_log)
            logger.warning(
                f"Webhook delivery to {url} failed on attempt {attempt + 1}: {e}"
            )

        except Exception as e:
            attempt_log["success"] = False
            attempt_log["error"] = f"Unexpected error: {str(e)}"
            attempts_log.append(attempt_log)
            logger.error(f"Webhook delivery to {url} failed with unexpected error: {e}")

        # Calculate delay before next retry
        if attempt < config.max_retries - 1:
            delay = config.retry_delays[min(attempt, len(config.retry_delays) - 1)]
            delay = min(delay, MAX_RETRY_DELAY)
            logger.info(f"Retrying webhook to {url} in {delay} seconds...")
            await asyncio.sleep(delay)

    # All retries exhausted
    final_error = (
        attempts_log[-1].get("error", "Unknown error")
        if attempts_log
        else "No attempts made"
    )
    logger.error(
        f"Webhook delivery to {url} failed after {config.max_retries} attempts. "
        f"Last error: {final_error}"
    )

    return (
        False,
        attempts_log[-1].get("status_code", 0) if attempts_log else 0,
        attempts_log,
    )


async def deliver_with_retry_simple(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> bool:
    """
    Simple webhook delivery with default retry logic.

    Returns True if delivered successfully, False otherwise.
    """
    success, _, _ = await deliver_with_retry(url, payload, headers)
    return success


# Decorator version for use with existing notification infrastructure
def webhook_retry(
    max_retries: int = MAX_RETRIES,
    retry_delays: list = None,
):
    """
    Decorator to add retry logic to webhook delivery functions.

    Usage:
        @webhook_retry(max_retries=3)
        async def send_webhook(url: str, payload: dict):
            ...
    """

    def decorator(func):
        async def wrapper(url: str, payload: dict, headers: dict = None):
            config = WebhookRetryConfig(
                max_retries=max_retries,
                retry_delays=retry_delays,
            )
            success, status_code, attempts = await deliver_with_retry(
                url, payload, headers, config
            )
            # Store attempts on the function for logging/audit
            wrapper.attempts = attempts
            return success, status_code

        return wrapper

    return decorator


async def test_webhook_delivery(url: str, test_payload: dict = None) -> Dict[str, Any]:
    """
    Test webhook delivery with a simple test payload.

    Returns diagnostic information about the delivery attempt.
    """
    if test_payload is None:
        test_payload = {
            "event": "test",
            "message": "Patch-SecOps Solution webhook test",
            "timestamp": datetime.utcnow().isoformat(),
        }

    success, status_code, attempts = await deliver_with_retry(url, test_payload)

    return {
        "url": url,
        "success": success,
        "final_status_code": status_code,
        "attempts": attempts,
    }
