"""Base backend interface for rate limiting storage."""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from rate_limiter.types import RateLimitConfig, RateLimitResult


@runtime_checkable
class Backend(Protocol):
    """Protocol defining the interface for rate limiting backends.

    All backends must implement these methods to be compatible with the rate limiter.
    This allows for easy swapping between different storage mechanisms (Redis, in-memory, etc.)
    """

    async def check_rate_limit(self, config: RateLimitConfig) -> RateLimitResult:
        """Check if a request is allowed under the rate limit.

        Args:
            config: Rate limit configuration containing rate, period, and key

        Returns:
            RateLimitResult containing decision and metadata

        Raises:
            BackendError: If the backend operation fails
        """
        ...

    async def reset(self, key: str) -> None:
        """Reset the rate limit for a specific key.

        Args:
            key: The rate limit key to reset

        Raises:
            BackendError: If the backend operation fails
        """
        ...

    async def get_usage(self, key: str) -> int:
        """Get current usage count for a key.

        Args:
            key: The rate limit key

        Returns:
            Current usage count

        Raises:
            BackendError: If the backend operation fails
        """
        ...

    async def close(self) -> None:
        """Close backend connections and cleanup resources."""
        ...

    async def health_check(self) -> bool:
        """Check if backend is healthy and accessible.

        Returns:
            True if backend is healthy, False otherwise
        """
        ...


class BaseBackend(ABC):
    """Abstract base class for backends, useful for implementation inheritance."""

    @abstractmethod
    async def check_rate_limit(self, config: RateLimitConfig) -> RateLimitResult:
        """Check if a request is allowed under the rate limit."""
        pass

    @abstractmethod
    async def reset(self, key: str) -> None:
        """Reset the rate limit for a specific key."""
        pass

    @abstractmethod
    async def get_usage(self, key: str) -> int:
        """Get current usage count for a key."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close backend connections and cleanup resources."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if backend is healthy and accessible."""
        pass

    async def __aenter__(self) -> "BaseBackend":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Async context manager exit."""
        await self.close()
