"""Splunk integration - send events to Splunk HTTP Event Collector."""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import json

import httpx

logger = logging.getLogger(__name__)


class SplunkIntegration:
    """Integration with Splunk via HTTP Event Collector (HEC)."""

    def __init__(
        self,
        hec_url: str,
        hec_token: str,
        index: str = "main",
        source: str = "Patch-SecOps Solution",
        sourcetype: str = "patchmaster:events",
        verify_ssl: bool = True,
    ):
        """
        Initialize Splunk integration.

        Args:
            hec_url: Splunk HEC endpoint URL (e.g., https://splunk:8088/services/collector)
            hec_token: HEC authentication token
            index: Splunk index to send events to
            source: Source field for events
            sourcetype: Sourcetype for events
            verify_ssl: Whether to verify SSL certificates
        """
        self.hec_url = hec_url.rstrip("/")
        self.hec_token = hec_token
        self.index = index
        self.source = source
        self.sourcetype = sourcetype
        self.verify_ssl = verify_ssl

    def _build_event(
        self,
        event: Dict[str, Any],
        host: Optional[str] = None,
        time: Optional[datetime] = None,
        fields: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Build a Splunk event payload."""
        payload = {
            "event": event,
            "host": host or "Patch-SecOps Solution",
            "source": self.source,
            "sourcetype": self.sourcetype,
            "index": self.index,
        }

        if time:
            payload["time"] = time.timestamp()

        if fields:
            # Fields must be prefixed with "fields." in Splunk events
            payload["fields"] = fields

        return payload

    async def send_event(
        self,
        event: Dict[str, Any],
        host: Optional[str] = None,
        time: Optional[datetime] = None,
        fields: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Send a single event to Splunk.

        Args:
            event: Event data to send
            host: Hostname to attribute event to
            time: Event timestamp
            fields: Additional fields for indexing

        Returns:
            True if successful, False otherwise
        """
        payload = self._build_event(event, host, time, fields)

        headers = {
            "Authorization": f"Splunk {self.hec_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                verify=self.verify_ssl,
            ) as client:
                response = await client.post(
                    self.hec_url,
                    json=payload,
                    headers=headers,
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("code") == 0:
                        logger.info(
                            f"Splunk event sent successfully: {event.get('event_type', 'unknown')}"
                        )
                        return True
                    else:
                        logger.error(f"Splunk error: {result.get('text', 'unknown')}")
                else:
                    logger.error(
                        f"Splunk HTTP error: {response.status_code} - {response.text[:200]}"
                    )

        except httpx.RequestError as e:
            logger.error(f"Splunk request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected Splunk error: {e}")

        return False

    async def send_batch(
        self,
        events: List[Dict[str, Any]],
        host: Optional[str] = None,
    ) -> tuple[int, int]:
        """
        Send multiple events in a batch.

        Args:
            events: List of events to send
            host: Hostname for events

        Returns:
            Tuple of (success_count, failure_count)
        """
        success_count = 0
        failure_count = 0

        for event in events:
            if await self.send_event(event, host=host):
                success_count += 1
            else:
                failure_count += 1

        logger.info(
            f"Splunk batch complete: {success_count} succeeded, {failure_count} failed"
        )
        return success_count, failure_count

    async def test_connection(self) -> bool:
        """Test the Splunk connection."""
        test_event = {
            "event_type": "test",
            "message": "Patch-SecOps Solution Splunk integration test",
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self.send_event(test_event)


# Event type helpers for common Patch-SecOps Solution events
async def send_patch_job_event(
    integration: SplunkIntegration,
    job_id: int,
    host_id: int,
    status: str,
    action: str,
    packages_count: int = 0,
):
    """Send a patch job event to Splunk."""
    event = {
        "event_type": "patch_job",
        "job_id": job_id,
        "host_id": host_id,
        "status": status,
        "action": action,
        "packages_count": packages_count,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return await integration.send_event(event)


async def send_host_event(
    integration: SplunkIntegration,
    host_id: int,
    hostname: str,
    event_type: str,
    details: Dict[str, Any],
):
    """Send a host event to Splunk."""
    event = {
        "event_type": event_type,
        "host_id": host_id,
        "hostname": hostname,
        "details": details,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return await integration.send_event(event)


async def send_cve_event(
    integration: SplunkIntegration,
    cve_id: str,
    severity: str,
    affected_hosts: List[int],
):
    """Send a CVE detection event to Splunk."""
    event = {
        "event_type": "cve_detected",
        "cve_id": cve_id,
        "severity": severity,
        "affected_host_count": len(affected_hosts),
        "affected_hosts": affected_hosts,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return await integration.send_event(event)


# Configuration validation
def validate_config(hec_url: str, hec_token: str) -> bool:
    """Validate Splunk configuration."""
    if not hec_url:
        return False
    if not hec_token:
        return False
    if not hec_url.startswith(("http://", "https://")):
        return False
    return True
