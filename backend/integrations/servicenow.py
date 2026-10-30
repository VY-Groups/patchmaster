"""ServiceNow integration - create and manage incidents via ServiceNow REST API."""

import logging
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class ServiceNowPriority(str, Enum):
    """ServiceNow priority levels."""

    CRITICAL = "1"
    HIGH = "2"
    MEDIUM = "3"
    LOW = "4"
    PLANNING = "5"


class ServiceNowUrgency(str, Enum):
    """ServiceNow urgency levels."""

    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"


class ServiceNowImpact(str, Enum):
    """ServiceNow impact levels."""

    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"


class ServiceNowIntegration:
    """Integration with ServiceNow for incident management."""

    def __init__(
        self,
        instance_url: str,
        username: str,
        password: str,
        table: str = "incident",
        verify_ssl: bool = True,
    ):
        """
        Initialize ServiceNow integration.

        Args:
            instance_url: ServiceNow instance URL (e.g., https://instance.service-now.com)
            username: ServiceNow username
            password: ServiceNow password
            table: Table to use (default: incident)
            verify_ssl: Whether to verify SSL certificates
        """
        self.instance_url = instance_url.rstrip("/")
        self.username = username
        self._password = password  # Store internal, access via property
        self.table = table
        self.verify_ssl = verify_ssl
        self._session = None

    @property
    def password(self) -> str:
        """Get password from environment or internal storage."""
        return os.getenv("SERVICENOW_PASSWORD", "") or self._password

    def _get_auth(self) -> tuple[str, str]:
        """Get authentication tuple."""
        return (self.username, self.password)

    async def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make an API request to ServiceNow."""
        url = f"{self.instance_url}/api/now/table/{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                verify=self.verify_ssl,
            ) as client:
                if method.upper() == "GET":
                    response = await client.get(
                        url, auth=self._get_auth(), headers=headers
                    )
                elif method.upper() == "POST":
                    response = await client.post(
                        url, json=data, auth=self._get_auth(), headers=headers
                    )
                elif method.upper() == "PATCH":
                    response = await client.patch(
                        url, json=data, auth=self._get_auth(), headers=headers
                    )
                else:
                    logger.error(f"Unsupported method: {method}")
                    return None

                if response.status_code in (200, 201):
                    if response.text:
                        return response.json()
                    return {}
                else:
                    logger.error(
                        f"ServiceNow HTTP {response.status_code}: {response.text[:200]}"
                    )

        except httpx.RequestError as e:
            logger.error(f"ServiceNow request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected ServiceNow error: {e}")

        return None

    async def create_incident(
        self,
        short_description: str,
        description: str,
        caller_id: Optional[str] = None,
        category: Optional[str] = None,
        contact_type: str = "web",
        priority: ServiceNowPriority = ServiceNowPriority.MEDIUM,
        urgency: ServiceNowUrgency = ServiceNowUrgency.MEDIUM,
        impact: ServiceNowImpact = ServiceNowImpact.MEDIUM,
        assigned_to: Optional[str] = None,
        business_service: Optional[str] = None,
        cmdb_ci: Optional[str] = None,  # Configuration Item
        additional_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Create a ServiceNow incident.

        Args:
            short_description: Brief description of the incident
            description: Full description
            caller_id: Caller's user ID
            category: Incident category
            contact_type: How the incident was reported
            priority: Priority level
            urgency: Urgency level
            impact: Impact level
            assigned_to: Assigned user
            business_service: Business service
            cmdb_ci: Configuration Item (e.g., host name)
            additional_fields: Additional custom fields

        Returns:
            Incident sys_id if successful, None otherwise
        """
        incident_data = {
            "short_description": short_description,
            "description": description,
            "contact_type": contact_type,
            "priority": priority.value,
            "urgency": urgency.value,
            "impact": impact.value,
        }

        if caller_id:
            incident_data["caller_id"] = caller_id
        if category:
            incident_data["category"] = category
        if assigned_to:
            incident_data["assigned_to"] = assigned_to
        if business_service:
            incident_data["business_service"] = business_service
        if cmdb_ci:
            incident_data["cmdb_ci"] = cmdb_ci
        if additional_fields:
            incident_data.update(additional_fields)

        result = await self._request("POST", self.table, incident_data)

        if result and "result" in result:
            sys_id = result["result"].get("sys_id")
            number = result["result"].get("number")
            logger.info(f"Created ServiceNow incident {number} (sys_id: {sys_id})")
            return sys_id

        return None

    async def update_incident(
        self,
        sys_id: str,
        **updates,
    ) -> bool:
        """
        Update an existing incident.

        Args:
            sys_id: Incident sys_id
            **updates: Fields to update

        Returns:
            True if successful, False otherwise
        """
        result = await self._request("PATCH", f"{self.table}/{sys_id}", updates)
        return result is not None

    async def add_comment(
        self,
        sys_id: str,
        comment: str,
        is_work_note: bool = False,
    ) -> bool:
        """
        Add a comment to an incident.

        Args:
            sys_id: Incident sys_id
            comment: Comment text
            is_work_note: Whether this is a work note (vs. comment)

        Returns:
            True if successful, False otherwise
        """
        field = "work_notes" if is_work_note else "comments"
        return await self.update_incident(sys_id, **{field: comment})

    async def get_incident(self, sys_id: str) -> Optional[Dict[str, Any]]:
        """Get an incident by sys_id."""
        result = await self._request("GET", f"{self.table}/{sys_id}")
        if result and "result" in result:
            return result["result"]
        return None

    async def test_connection(self) -> bool:
        """Test the ServiceNow connection."""
        # Try to get the API version as a connection test
        url = f"{self.instance_url}/api/now/status"
        headers = {"Accept": "application/json"}

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                verify=self.verify_ssl,
            ) as client:
                response = await client.get(url, auth=self._get_auth(), headers=headers)
                return response.status_code in (200, 404)  # 404 is OK - API exists
        except Exception:
            return False


# Helper functions for common Patch-SecOps Solution events
async def create_patch_failure_incident(
    integration: ServiceNowIntegration,
    host_id: int,
    hostname: str,
    job_id: int,
    error_message: str,
    caller_id: Optional[str] = None,
) -> Optional[str]:
    """Create an incident for a patch failure."""
    return await integration.create_incident(
        short_description=f"Patch failure on {hostname} (Job #{job_id})",
        description=(
            f"Patch job #{job_id} failed on host {hostname} (ID: {host_id})\n\n"
            f"Error: {error_message}\n\n"
            f"Time: {datetime.utcnow().isoformat()}"
        ),
        caller_id=caller_id,
        category="Software",
        priority=ServiceNowPriority.MEDIUM,
        cmdb_ci=hostname,
    )


async def create_cve_alert_incident(
    integration: ServiceNowIntegration,
    cve_id: str,
    severity: str,
    affected_hosts: List[int],
    caller_id: Optional[str] = None,
) -> Optional[str]:
    """Create an incident for a CVE alert."""
    severity_priority = {
        "critical": ServiceNowPriority.CRITICAL,
        "high": ServiceNowPriority.HIGH,
        "medium": ServiceNowPriority.MEDIUM,
        "low": ServiceNowPriority.LOW,
    }

    return await integration.create_incident(
        short_description=f"CVE Alert: {cve_id} ({severity} severity)",
        description=(
            f"CVE {cve_id} detected with {severity} severity\n\n"
            f"Affected hosts: {len(affected_hosts)}\n"
            f"Host IDs: {', '.join(map(str, affected_hosts))}\n\n"
            f"Time: {datetime.utcnow().isoformat()}"
        ),
        caller_id=caller_id,
        category="Security",
        priority=severity_priority.get(severity.lower(), ServiceNowPriority.MEDIUM),
    )


# Configuration validation
def validate_config(instance_url: str, username: str, password: str) -> bool:
    """Validate ServiceNow configuration."""
    if not instance_url:
        return False
    if not username or not password:
        return False
    if not instance_url.startswith(("http://", "https://")):
        return False
    return True
