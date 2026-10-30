"""Sumo Logic integration - send events to Sumo Logic HTTP Source."""

import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class SumoLogicIntegration:
    """Integration with Sumo Logic via HTTP Source."""

    def __init__(
        self,
        http_source_url: str,
        source_category: str = "Patch-SecOps Solution",
        source_name: str = "Patch-SecOps Solution",
        verify_ssl: bool = True,
    ):
        """
        Initialize Sumo Logic integration.

        Args:
            http_source_url: Sumo Logic HTTP Source collector URL
            source_category: Source category for events
            source_name: Source name identifier
            verify_ssl: Whether to verify SSL certificates
        """
        self.http_source_url = http_source_url.rstrip("/")
        self.source_category = source_category
        self.source_name = source_name
        self.verify_ssl = verify_ssl

    def _build_headers(self) -> Dict[str, str]:
        """Build headers for Sumo Logic requests."""
        return {
            "Content-Type": "application/json",
            "X-Sumo-Name": self.source_name,
            "X-Sumo-Category": self.source_category,
        }

    async def send_event(
        self,
        event: Dict[str, Any],
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Send a single event to Sumo Logic.

        Args:
            event: Event data to send
            timestamp: Event timestamp (defaults to now)

        Returns:
            True if successful, False otherwise
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        # Sumo Logic expects specific format
        payload = {
            "_timestamp": int(timestamp.timestamp() * 1000),
            "message": json.dumps(event),
        }

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                verify=self.verify_ssl,
            ) as client:
                response = await client.post(
                    self.http_source_url,
                    json=payload,
                    headers=self._build_headers(),
                )

                if response.status_code in (200, 204):
                    logger.info(
                        f"Sumo Logic event sent: {event.get('event_type', 'unknown')}"
                    )
                    return True
                else:
                    logger.error(f"Sumo Logic HTTP error: {response.status_code}")

        except httpx.RequestError as e:
            logger.error(f"Sumo Logic request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected Sumo Logic error: {e}")

        return False

    async def send_batch(
        self,
        events: List[Dict[str, Any]],
    ) -> tuple[int, int]:
        """
        Send multiple events in a batch.

        Args:
            events: List of events to send

        Returns:
            Tuple of (success_count, failure_count)
        """
        success_count = 0
        failure_count = 0

        for event in events:
            if await self.send_event(event):
                success_count += 1
            else:
                failure_count += 1

        logger.info(
            f"Sumo Logic batch complete: {success_count} succeeded, {failure_count} failed"
        )
        return success_count, failure_count

    async def test_connection(self) -> bool:
        """Test the Sumo Logic connection."""
        test_event = {
            "event_type": "test",
            "message": "Patch-SecOps Solution Sumo Logic integration test",
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self.send_event(test_event)


# Helper function for common Sumo Logic messages
async def send_log_message(
    integration: SumoLogicIntegration,
    level: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
):
    """Send a log message to Sumo Logic."""
    event = {
        "event_type": "log",
        "level": level,
        "message": message,
        "context": context or {},
        "timestamp": datetime.utcnow().isoformat(),
    }
    return await integration.send_event(event)


# Configuration validation
def validate_config(http_source_url: str) -> bool:
    """Validate Sumo Logic configuration."""
    if not http_source_url:
        return False
    if not http_source_url.startswith(("http://", "https://")):
        return False
    return True
