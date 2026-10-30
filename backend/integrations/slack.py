"""
Slack Integration for Patch-SecOps Solution.

Supports channels, DMs, threads, and rich message formatting (blocks).
Maps Patch-SecOps Solution events to Slack messages.
"""

import os
from enum import Enum
from typing import Any, Optional

import httpx


class SlackChannelType(str, Enum):
    """Slack channel types."""

    CHANNEL = "channel"
    DM = "im"
    GROUP = "mpim"


class SlackMessageType(str, Enum):
    """Slack message formatting types."""

    SIMPLE = "simple"
    RICH = "rich"
    COMPACT = "compact"


# Map Patch-SecOps Solution events to Slack message templates
EVENT_MESSAGE_TEMPLATES = {
    "patch_failed": {
        "emoji": ":x:",
        "color": "danger",
        "title": "Patch Failed",
    },
    "patch_success": {
        "emoji": ":white_check_mark:",
        "color": "good",
        "title": "Patch Completed",
    },
    "cve_critical": {
        "emoji": ":warning:",
        "color": "danger",
        "title": "Critical CVE Detected",
    },
    "cve_warning": {
        "emoji": ":large_yellow_circle:",
        "color": "warning",
        "title": "CVE Warning",
    },
    "host_offline": {
        "emoji": ":red_circle:",
        "color": "danger",
        "title": "Host Offline",
    },
    "compliance_failure": {
        "emoji": ":rotating_light:",
        "color": "danger",
        "title": "Compliance Failure",
    },
    "job_started": {
        "emoji": ":gear:",
        "color": "#439FE0",
        "title": "Patch Job Started",
    },
    "schedule_missed": {
        "emoji": ":calendar:",
        "color": "warning",
        "title": "Schedule Missed",
    },
}


class SlackIntegration:
    """Slack API integration client."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        bot_token: Optional[str] = None,
        default_channel: str = "#patchmaster",
    ):
        """Initialize Slack client.

        Args:
            webhook_url: Incoming webhook URL for simple messages
            bot_token: Slack Bot User OAuth token (for advanced features)
            default_channel: Default channel for notifications
        """
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN", "")
        self.default_channel = default_channel or os.getenv(
            "SLACK_DEFAULT_CHANNEL", "#patchmaster"
        )

        self._client: Optional[httpx.AsyncClient] = None

    @property
    def auth_headers(self) -> dict:
        """Return authentication headers for bot API."""
        if not self.bot_token:
            return {}
        return {"Authorization": f"Bearer {self.bot_token}"}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://slack.com/api",
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    **self.auth_headers,
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_webhook_message(
        self,
        text: str,
        channel: Optional[str] = None,
        username: str = "Patch-SecOps Solution",
        icon_emoji: str = ":robot_face:",
    ) -> dict[str, Any]:
        """Send message via incoming webhook.

        Args:
            text: Message text
            channel: Override default channel
            username: Bot username
            icon_emoji: Bot icon

        Returns:
            Slack API response
        """
        if not self.webhook_url:
            raise ValueError("Slack webhook URL is required")

        payload = {
            "text": text,
            "channel": channel or self.default_channel,
            "username": username,
            "icon_emoji": icon_emoji,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            return response.json()

    async def send_message(
        self,
        text: str,
        channel: Optional[str] = None,
        blocks: Optional[list[dict]] = None,
        thread_ts: Optional[str] = None,
        username: str = "Patch-SecOps Solution",
        icon_emoji: str = ":robot_face:",
    ) -> dict[str, Any]:
        """Send message via chat.postMessage API.

        Args:
            text: Fallback text for notifications
            channel: Channel to post to (e.g., #general, @user)
            blocks: Rich message blocks (Slack Block Kit)
            thread_ts: Thread timestamp to reply in
            username: Bot username
            icon_emoji: Bot icon

        Returns:
            Slack API response with 'ts' (timestamp)
        """
        if not self.bot_token:
            raise ValueError("Slack bot token is required for chat.postMessage")

        client = await self._get_client()

        payload: dict[str, Any] = {
            "channel": channel or self.default_channel,
            "text": text,
            "username": username,
            "icon_emoji": icon_emoji,
        }

        if blocks:
            payload["blocks"] = blocks

        if thread_ts:
            payload["thread_ts"] = thread_ts

        response = await client.post("/chat.postMessage", json=payload)
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            raise Exception(f"Slack API error: {result.get('error')}")

        return result

    async def send_rich_message(
        self,
        event_type: str,
        title: Optional[str] = None,
        fields: Optional[list[dict[str, str]]] = None,
        color: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send rich message with blocks for a Patch-SecOps Solution event.

        Args:
            event_type: Type of event (from EVENT_MESSAGE_TEMPLATES)
            title: Override title
            fields: List of field dicts with 'title' and 'value'
            color: Override color
            channel: Override channel

        Returns:
            Slack API response
        """
        template = EVENT_MESSAGE_TEMPLATES.get(event_type, {})

        emoji = template.get("emoji", ":bell:")
        template_color = template.get("color", "#439FE0")
        template_title = template.get("title", "Patch-SecOps Solution Alert")

        # Build rich message blocks
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {title or template_title}",
                    "emoji": True,
                },
            }
        ]

        if fields:
            fields_block: list[dict[str, Any]] = []
            for field in fields:
                fields_block.append(
                    {
                        "type": "mrkdwn",
                        "text": f"*{field.get('title', '')}*\n{field.get('value', '')}",
                    }
                )
            blocks.append(
                {
                    "type": "section",
                    "fields": fields_block[:10],  # Max 10 fields
                }
            )

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Sent from *PatchMaster* at {self._timestamp()}",
                    }
                ],
            }
        )

        # Send as webhook for simplicity, or use chat.postMessage
        if self.webhook_url:
            # Fallback to simple message via webhook
            text = f"{emoji} {title or template_title}"
            if fields:
                for f in fields:
                    text += f"\n*{f.get('title', '')}*: {f.get('value', '')}"
            return await self.send_webhook_message(
                text=text, channel=channel, icon_emoji=emoji
            )

        return await self.send_message(
            text=title or template_title,
            channel=channel,
            blocks=blocks,
        )

    def _timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime

        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    async def list_channels(
        self, types: Optional[list[str]] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List available Slack channels.

        Args:
            types: Channel types to filter (public_channel, private_channel, im, mpim)
            limit: Maximum results

        Returns:
            List of channels
        """
        if not self.bot_token:
            raise ValueError("Slack bot token is required")

        client = await self._get_client()

        params: dict[str, Any] = {"limit": limit}
        if types:
            params["types"] = ",".join(types)

        response = await client.get("/conversations.list", params=params)
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            raise Exception(f"Slack API error: {result.get('error')}")

        return result.get("channels", [])

    async def post_to_channel(
        self,
        channel: str,
        text: str,
        blocks: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """Post a message to a channel.

        Args:
            channel: Channel name (e.g., #general)
            text: Message text
            blocks: Optional rich blocks

        Returns:
            API response
        """
        # Ensure channel has # prefix
        if not channel.startswith("#") and not channel.startswith("@"):
            channel = f"#{channel}"

        return await self.send_message(
            text=text,
            channel=channel,
            blocks=blocks,
        )

    async def send_dm(
        self, user_id: str, text: str, blocks: Optional[list[dict]] = None
    ) -> dict[str, Any]:
        """Send a direct message to a user.

        Args:
            user_id: Slack user ID
            text: Message text
            blocks: Optional rich blocks

        Returns:
            API response
        """
        return await self.send_message(
            text=text,
            channel=user_id,
            blocks=blocks,
        )


async def send_patch_job_notification(
    event_type: str,
    host_name: str,
    status: str,
    details: Optional[str] = None,
) -> dict[str, Any]:
    """Send notification about a patch job.

    Args:
        event_type: Type of event (patch_failed, patch_success, etc.)
        host_name: Host name
        status: Job status
        details: Optional details

    Returns:
        Slack API response
    """
    integration = SlackIntegration()

    fields = [
        {"title": "Host", "value": host_name},
        {"title": "Status", "value": status},
    ]
    if details:
        fields.append({"title": "Details", "value": details})

    return await integration.send_rich_message(
        event_type=event_type,
        fields=fields,
    )


async def send_cve_alert(
    cve_id: str,
    severity: str,
    affected_count: int,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Send CVE alert to Slack.

    Args:
        cve_id: CVE identifier
        severity: Severity level
        affected_count: Number of affected hosts
        description: Optional description

    Returns:
        Slack API response
    """
    integration = SlackIntegration()

    event_type = (
        "cve_critical" if severity.lower() in ["critical", "high"] else "cve_warning"
    )

    fields = [
        {"title": "CVE", "value": cve_id},
        {"title": "Severity", "value": severity},
        {"title": "Affected Hosts", "value": str(affected_count)},
    ]
    if description:
        fields.append({"title": "Description", "value": description[:100]})

    return await integration.send_rich_message(
        event_type=event_type,
        fields=fields,
    )


# Module-level convenience function
_default_integration: Optional[SlackIntegration] = None


def get_slack_integration() -> SlackIntegration:
    """Get default Slack integration instance.

    Returns:
        SlackIntegration instance (may not be configured)
    """
    global _default_integration
    if _default_integration is None:
        _default_integration = SlackIntegration()
    return _default_integration
