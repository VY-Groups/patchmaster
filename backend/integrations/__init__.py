"""External integrations for Patch-SecOps Solution.

Provides integration modules for:
- Jira: Create and manage Jira tickets
- Slack: Send notifications to Slack channels
- Splunk: Send events to Splunk HTTP Event Collector
- Sumo Logic: Send events to Sumo Logic HTTP Source
- ServiceNow: Create incidents via ServiceNow REST API
- Custom: Framework for custom integrations
"""

from .jira import (
    JiraIntegration,
    JiraIssueType,
    JiraPriority,
    create_patch_failure_ticket,
    create_cve_alert_ticket,
    update_ticket_status,
)
from .slack import (
    SlackIntegration,
    send_patch_job_notification,
    send_cve_alert,
)
from .splunk import (
    SplunkIntegration,
    send_patch_job_event,
    send_host_event,
    send_cve_event,
)
from .sumo_logic import SumoLogicIntegration, send_log_message
from .servicenow import (
    ServiceNowIntegration,
    ServiceNowPriority,
    ServiceNowUrgency,
    ServiceNowImpact,
    create_patch_failure_incident,
    create_cve_alert_incident,
)
from .custom import (
    BaseIntegration,
    CustomIntegrationRegistry,
    IntegrationCategory,
    IntegrationCapability,
    event_dispatcher,
    create_custom_integration,
    get_integration_health,
    integration,
)

__all__ = [
    # Jira
    "JiraIntegration",
    "JiraIssueType",
    "JiraPriority",
    "create_patch_failure_ticket",
    "create_cve_alert_ticket",
    "update_ticket_status",
    # Slack
    "SlackIntegration",
    "send_patch_job_notification",
    "send_cve_alert",
    # Splunk
    "SplunkIntegration",
    "send_patch_job_event",
    "send_host_event",
    "send_cve_event",
    # Sumo Logic
    "SumoLogicIntegration",
    "send_log_message",
    # ServiceNow
    "ServiceNowIntegration",
    "ServiceNowPriority",
    "ServiceNowUrgency",
    "ServiceNowImpact",
    "create_patch_failure_incident",
    "create_cve_alert_incident",
    # Custom
    "BaseIntegration",
    "CustomIntegrationRegistry",
    "IntegrationCategory",
    "IntegrationCapability",
    "event_dispatcher",
    "create_custom_integration",
    "get_integration_health",
    "integration",
]
