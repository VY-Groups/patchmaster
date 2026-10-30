"""
Jira Integration for Patch-SecOps Solution.

Supports Jira Cloud and Server instances via REST API.
Creates issues, updates status, adds comments.
Maps Patch-SecOps Solution events to Jira workflow states.
"""

import os
from enum import Enum
from typing import Any, Optional
from functools import cached_property

import httpx


class JiraIssueType(str, Enum):
    """Jira issue types for patch-related tickets."""

    BUG = "Bug"
    TASK = "Task"
    STORY = "Story"
    IMPROVEMENT = "Improvement"
    SUB_TASK = "Sub-task"


class JiraPriority(str, Enum):
    """Jira priority mapping from Patch-SecOps Solution severity."""

    HIGHEST = "Highest"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    LOWEST = "Lowest"


class JiraWorkflowStatus(str, Enum):
    """Jira workflow status mapping."""

    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    IN_REVIEW = "In Review"
    RESOLVED = "Resolved"
    CLOSED = "Closed"


# Map Patch-SecOps Solution event types to Jira issue types and priorities
EVENT_ISSUE_TYPE_MAP = {
    "patch_failed": (JiraIssueType.BUG, JiraPriority.HIGH),
    "patch_success": (JiraIssueType.TASK, JiraPriority.MEDIUM),
    "cve_critical": (JiraIssueType.BUG, JiraPriority.HIGHEST),
    "cve_warning": (JiraIssueType.TASK, JiraPriority.MEDIUM),
    "host_offline": (JiraIssueType.TASK, JiraPriority.LOW),
    "compliance_failure": (JiraIssueType.BUG, JiraPriority.HIGH),
    "schedule_missed": (JiraIssueType.TASK, JiraPriority.MEDIUM),
}

# Map Patch-SecOps Solution action types to Jira transitions
ACTION_TRANSITION_MAP = {
    "start_progress": "Start Progress",
    "resolve": "Resolve",
    "close": "Close",
    "reopen": "Reopen",
}


class JiraIntegration:
    """Jira REST API integration client."""

    def __init__(
        self,
        url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
        project_key: str = "PATCH",
    ):
        """Initialize Jira client.

        Args:
            url: Jira instance URL (e.g., https://company.atlassian.net)
            email: User email for authentication
            api_token: API token (from https://id.atlassian.com/manage-profile/security/api-token)
            project_key: Jira project key (default: PATCH)
        """
        self.url = (url or os.getenv("JIRA_URL", "")).rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL", "")
        self._api_token = api_token  # Store internal, access via property
        self.project_key = project_key or os.getenv("JIRA_PROJECT_KEY", "PATCH")

        if not self.url:
            raise ValueError("Jira URL is required. Set JIRA_URL env var.")

        self._client: Optional[httpx.AsyncClient] = None

    @property
    def api_token(self) -> str:
        """Get API token from environment or internal storage."""
        return os.getenv("JIRA_API_TOKEN", "") or (self._api_token or "")

    @property
    def auth(self) -> dict:
        """Return authentication headers."""
        import base64

        credentials = f"{self.email}:{self.api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **self.auth,
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_issue(
        self,
        summary: str,
        description: str = "",
        issue_type: JiraIssueType = JiraIssueType.TASK,
        priority: JiraPriority = JiraPriority.MEDIUM,
        labels: Optional[list[str]] = None,
        custom_fields: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a Jira issue.

        Args:
            summary: Issue summary/title
            description: Issue description (supports Jira wiki markup)
            issue_type: Type of issue to create
            priority: Priority level
            labels: Optional list of labels
            custom_fields: Optional custom field values

        Returns:
            Created issue data including 'key' and 'id'
        """
        client = await self._get_client()

        data = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": description or summary}
                            ],
                        }
                    ],
                },
                "issuetype": {"name": issue_type.value},
                "priority": {"name": priority.value},
            }
        }

        if labels:
            data["fields"]["labels"] = labels

        if custom_fields:
            data["fields"].update(custom_fields)

        response = await client.post("/rest/api/3/issue", json=data)
        response.raise_for_status()
        return response.json()

    async def update_issue(
        self,
        issue_key: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[JiraPriority] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Update an existing Jira issue.

        Args:
            issue_key: Jira issue key (e.g., 'PATCH-123')
            summary: New summary
            description: New description
            priority: New priority
            labels: New labels (replaces existing)

        Returns:
            Update response
        """
        client = await self._get_client()

        fields: dict[str, Any] = {}
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }
        if priority:
            fields["priority"] = {"name": priority.value}
        if labels is not None:
            fields["labels"] = labels

        if not fields:
            return {"updated": False, "reason": "no_fields_to_update"}

        data = {"fields": fields}
        response = await client.put(f"/rest/api/3/issue/{issue_key}", json=data)
        response.raise_for_status()
        return {"updated": True, "key": issue_key}

    async def transition_issue(self, issue_key: str, transition: str) -> dict[str, Any]:
        """Transition an issue to a new status.

        Args:
            issue_key: Jira issue key
            transition: Transition name (e.g., 'Start Progress', 'Resolve')

        Returns:
            Transition response
        """
        client = await self._get_client()

        # First get available transitions
        response = await client.get(f"/rest/api/3/issue/{issue_key}/transitions")
        response.raise_for_status()
        transitions_data = response.json()
        transitions = transitions_data.get("transitions", [])

        # Find matching transition
        target_transition = None
        for t in transitions:
            if t.get("name", "").lower() == transition.lower():
                target_transition = t
                break

        if not target_transition:
            return {
                "success": False,
                "error": f"Transition '{transition}' not found",
                "available_transitions": [t.get("name") for t in transitions],
            }

        # Execute transition
        data = {"transition": {"id": target_transition["id"]}}
        response = await client.post(
            f"/rest/api/3/issue/{issue_key}/transitions", json=data
        )
        response.raise_for_status()
        return {"success": True, "key": issue_key, "transition": transition}

    async def add_comment(self, issue_key: str, comment: str) -> dict[str, Any]:
        """Add a comment to an issue.

        Args:
            issue_key: Jira issue key
            comment: Comment text (supports Jira wiki markup)

        Returns:
            Created comment data
        """
        client = await self._get_client()

        data = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}],
                    }
                ],
            }
        }

        response = await client.post(
            f"/rest/api/3/issue/{issue_key}/comment", json=data
        )
        response.raise_for_status()
        return response.json()

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Get issue details.

        Args:
            issue_key: Jira issue key

        Returns:
            Issue data
        """
        client = await self._get_client()
        response = await client.get(f"/rest/api/3/issue/{issue_key}")
        response.raise_for_status()
        return response.json()

    async def search_issues(
        self, jql: str, max_results: int = 50
    ) -> list[dict[str, Any]]:
        """Search issues using JQL.

        Args:
            jql: JQL query string
            max_results: Maximum results to return

        Returns:
            List of issues
        """
        client = await self._get_client()

        data = {"jql": jql, "maxResults": max_results}
        response = await client.post("/rest/api/3/search", json=data)
        response.raise_for_status()
        result = response.json()
        return result.get("issues", [])


async def create_patch_failure_ticket(
    host_name: str,
    error_message: str,
    package_name: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Jira ticket for a patch failure.

    Args:
        host_name: Host where patch failed
        error_message: Error details
        package_name: Optional package that failed

    Returns:
        Created issue data
    """
    issue_type, priority = EVENT_ISSUE_TYPE_MAP.get(
        "patch_failed", (JiraIssueType.BUG, JiraPriority.HIGH)
    )

    summary = f"Patch Failed: {host_name}"
    description_parts = [
        f"Patch failed on host: {host_name}",
    ]
    if package_name:
        description_parts.append(f"Package: {package_name}")
    description_parts.append(f"Error: {error_message}")

    integration = JiraIntegration()
    return await integration.create_issue(
        summary=summary,
        description="\n".join(description_parts),
        issue_type=issue_type,
        priority=priority,
        labels=["patch-failure", "patchmaster"],
    )


async def create_cve_alert_ticket(
    cve_id: str,
    severity: str,
    affected_hosts: list[str],
    description: str = "",
) -> dict[str, Any]:
    """Create a Jira ticket for a critical CVE.

    Args:
        cve_id: CVE identifier (e.g., CVE-2024-1234)
        severity: Severity level
        affected_hosts: List of affected host names
        description: CVE description

    Returns:
        Created issue data
    """
    issue_type, priority = EVENT_ISSUE_TYPE_MAP.get(
        "cve_critical", (JiraIssueType.BUG, JiraPriority.HIGHEST)
    )

    summary = f"Critical CVE Detected: {cve_id}"
    description_parts = [
        f"CVE: {cve_id}",
        f"Severity: {severity}",
        f"Affected hosts ({len(affected_hosts)}): {', '.join(affected_hosts[:5])}",
    ]
    if len(affected_hosts) > 5:
        description_parts.append(f"... and {len(affected_hosts) - 5} more")
    if description:
        description_parts.append(f"Description: {description}")

    integration = JiraIntegration()
    return await integration.create_issue(
        summary=summary,
        description="\n".join(description_parts),
        issue_type=issue_type,
        priority=priority,
        labels=["cve-alert", "security", "patchmaster"],
    )


async def update_ticket_status(issue_key: str, action: str) -> dict[str, Any]:
    """Update ticket status based on action.

    Args:
        issue_key: Jira issue key
        action: Action to perform (start_progress, resolve, close, reopen)

    Returns:
        Transition result
    """
    transition = ACTION_TRANSITION_MAP.get(action)
    if not transition:
        return {"success": False, "error": f"Unknown action: {action}"}

    integration = JiraIntegration()
    return await integration.transition_issue(issue_key, transition)


# Module-level convenience function
_default_integration: Optional[JiraIntegration] = None


def get_jira_integration() -> JiraIntegration:
    """Get default Jira integration instance.

    Returns:
        JiraIntegration instance

    Raises:
        ValueError: If Jira is not configured
    """
    global _default_integration
    if _default_integration is None:
        _default_integration = JiraIntegration()
    return _default_integration
