"""
Custom Integration Framework for Patch-SecOps Solution.

Provides a base class for creating custom integrations.
Supports registration, configuration, and event dispatching.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Optional

import httpx


logger = logging.getLogger(__name__)


class IntegrationCategory(str, Enum):
    """Categories for custom integrations."""

    MONITORING = "monitoring"
    TICKETING = "ticketing"
    CMDB = "cmdb"
    SECURITY = "security"
    NOTIFICATION = "notification"
    CUSTOM = "custom"


class IntegrationCapability(str, Enum):
    """Capabilities that integrations can provide."""

    CREATE_TICKET = "create_ticket"
    UPDATE_TICKET = "update_ticket"
    SEND_NOTIFICATION = "send_notification"
    SYNC_ASSET = "sync_asset"
    EXECUTE_ACTION = "execute_action"
    QUERY_DATA = "query_data"


class BaseIntegration(ABC):
    """Base class for custom integrations.

    Subclass this to create custom integrations.
    """

    name: str = "base_integration"
    description: str = "Custom integration"
    category: IntegrationCategory = IntegrationCategory.CUSTOM
    capabilities: list[IntegrationCapability] = []

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize integration with configuration.

        Args:
            config: Integration-specific configuration
        """
        self.config = config or {}
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the integration (e.g., test connection).

        Returns:
            True if initialization successful

        Raises:
            Exception: If initialization fails
        """
        self._initialized = True
        return True

    async def shutdown(self):
        """Clean up integration resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if integration is initialized."""
        return self._initialized

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            timeout = self.config.get("timeout", 30.0)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check integration health.

        Returns:
            Health status dict with 'healthy' bool and optional 'message'
        """
        pass

    async def send_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Send event to integration.

        Override this in subclasses to handle custom events.

        Args:
            event_type: Type of event
            payload: Event data

        Returns:
            Integration response
        """
        return {"status": "ok", "event_type": event_type}


class WebhookIntegration(BaseIntegration):
    """Generic webhook integration."""

    name = "webhook"
    description = "Send events to HTTP webhooks"
    category = IntegrationCategory.NOTIFICATION
    capabilities = [IntegrationCapability.SEND_NOTIFICATION]

    def __init__(self, config: Optional[dict[str, Any]] = None):
        super().__init__(config)
        self.webhook_url = self.config.get("webhook_url", "")
        self.method = self.config.get("method", "POST").upper()

    async def health_check(self) -> dict[str, Any]:
        """Check webhook endpoint health."""
        if not self.webhook_url:
            return {"healthy": False, "message": "No webhook URL configured"}

        try:
            client = await self._get_client()
            # Just check if URL is reachable
            response = await client.head(self.webhook_url)
            return {
                "healthy": response.status_code < 500,
                "status_code": response.status_code,
            }
        except Exception as e:
            return {"healthy": False, "message": str(e)}

    async def send_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Send event to webhook."""
        if not self.webhook_url:
            raise ValueError("Webhook URL not configured")

        client = await self._get_client()

        data = {
            "source": "patchmaster",
            "event_type": event_type,
            "payload": payload,
        }

        response = await client.request(
            self.method,
            self.webhook_url,
            json=data,
        )

        if response.status_code >= 400:
            return {
                "status": "error",
                "message": f"HTTP {response.status_code}: {response.text[:200]}",
            }

        return {"status": "ok", "event_type": event_type}


class CustomIntegrationRegistry:
    """Registry for custom integration classes.

    Use this to register and instantiate custom integrations.
    """

    _integrations: dict[str, type[BaseIntegration]] = {}

    @classmethod
    def register(
        cls, integration_class: type[BaseIntegration]
    ) -> type[BaseIntegration]:
        """Register an integration class.

        Args:
            integration_class: Integration class to register

        Returns:
            The registered class
        """
        instance = integration_class()
        cls._integrations[instance.name] = integration_class
        logger.info(f"Registered integration: {instance.name}")
        return integration_class

    @classmethod
    def get(cls, name: str) -> Optional[type[BaseIntegration]]:
        """Get an integration class by name.

        Args:
            name: Integration name

        Returns:
            Integration class or None
        """
        return cls._integrations.get(name)

    @classmethod
    def list_integrations(cls) -> list[dict[str, Any]]:
        """List all registered integrations.

        Returns:
            List of integration metadata
        """
        result = []
        for name, integration_class in cls._integrations.items():
            instance = integration_class()
            result.append(
                {
                    "name": instance.name,
                    "description": instance.description,
                    "category": instance.category.value,
                    "capabilities": [c.value for c in instance.capabilities],
                }
            )
        return result

    @classmethod
    def create_integration(
        cls,
        name: str,
        config: Optional[dict[str, Any]] = None,
    ) -> Optional[BaseIntegration]:
        """Create an integration instance.

        Args:
            name: Integration name
            config: Integration configuration

        Returns:
            Integration instance or None
        """
        integration_class = cls.get(name)
        if not integration_class:
            return None
        return integration_class(config=config)


# Register built-in integrations
CustomIntegrationRegistry.register(WebhookIntegration)


# Event dispatcher for integrations
class IntegrationEventDispatcher:
    """Dispatches events to registered integrations."""

    def __init__(self):
        self._handlers: dict[str, list[BaseIntegration]] = {}
        self._lock = asyncio.Lock()

    async def register_handler(
        self,
        event_type: str,
        integration: BaseIntegration,
    ):
        """Register an integration to handle an event type.

        Args:
            event_type: Event type to handle
            integration: Integration instance
        """
        async with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            if integration not in self._handlers[event_type]:
                self._handlers[event_type].append(integration)
                logger.info(f"Registered {integration.name} for {event_type}")

    async def unregister_handler(
        self,
        event_type: str,
        integration: BaseIntegration,
    ):
        """Unregister an integration from an event type.

        Args:
            event_type: Event type
            integration: Integration instance
        """
        async with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type].remove(integration)

    async def dispatch(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Dispatch an event to all registered integrations.

        Args:
            event_type: Type of event
            payload: Event data

        Returns:
            List of integration responses
        """
        async with self._lock:
            handlers = list(self._handlers.get(event_type, []))

        if not handlers:
            return []

        results = []
        for integration in handlers:
            try:
                if not integration.is_initialized:
                    await integration.initialize()

                result = await integration.send_event(event_type, payload)
                results.append(
                    {
                        "integration": integration.name,
                        "result": result,
                    }
                )
            except Exception as e:
                logger.error(f"Integration {integration.name} failed: {e}")
                results.append(
                    {
                        "integration": integration.name,
                        "error": str(e),
                    }
                )

        return results


# Global event dispatcher
event_dispatcher = IntegrationEventDispatcher()


# Decorator for easy integration registration
def integration(
    name: str,
    description: str = "",
    category: IntegrationCategory = IntegrationCategory.CUSTOM,
    capabilities: Optional[list[IntegrationCapability]] = None,
):
    """Decorator to register a custom integration class.

    Usage:
        @integration(
            name="my_integration",
            description="My custom integration",
            category=IntegrationCategory.MONITORING,
            capabilities=[IntegrationCapability.SEND_NOTIFICATION]
        )
        class MyIntegration(BaseIntegration):
            ...
    """

    def decorator(cls: type[BaseIntegration]) -> type[BaseIntegration]:
        original_init = cls.__init__ if hasattr(cls, "__init__") else None

        def new_init(self, config=None):
            self.name = name
            self.description = description
            self.category = category
            self.capabilities = capabilities or []
            if original_init:
                original_init(self, config)
            else:
                super(cls, self).__init__(config)

        cls.__init__ = new_init
        cls.name = name
        cls.description = description
        cls.category = category
        cls.capabilities = capabilities or []

        CustomIntegrationRegistry.register(cls)
        return cls

    return decorator


# Helper functions
def create_custom_integration(
    name: str,
    config: Optional[dict[str, Any]] = None,
) -> Optional[BaseIntegration]:
    """Create a custom integration instance.

    Args:
        name: Integration name
        config: Configuration dict

    Returns:
        Integration instance or None
    """
    return CustomIntegrationRegistry.create_integration(name, config)


def get_integration_health(
    name: str,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Get health status of an integration.

    Args:
        name: Integration name
        config: Optional config override

    Returns:
        Health status dict
    """
    integration = create_custom_integration(name, config)
    if not integration:
        return {"healthy": False, "message": f"Unknown integration: {name}"}

    return asyncio.run(integration.health_check())
