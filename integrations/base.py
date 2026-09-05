"""Shared base interface for all Relationship OS integration adapters."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple
from packages.shared.src.models import CanonicalMessageEvent


class IntegrationAdapter(ABC):
    """Abstract interface that every integration adapter must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Integration name (e.g. 'discord', 'webhook', 'signal')."""
        pass

    @abstractmethod
    async def send(self, event: CanonicalMessageEvent) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Deliver canonical message event to external channel.
        Returns:
            (success: bool, external_message_id: Optional[str], failure_reason: Optional[str])
        """
        pass

    @abstractmethod
    async def validate_config(self) -> Tuple[bool, str]:
        """Validate required secrets and endpoints."""
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Diagnostic health status of integration."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Gracefully release HTTP clients and connections."""
        pass
