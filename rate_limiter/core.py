"""Core rate limiter with graceful degradation."""

import logging
from typing import Any

from rate_limiter.backends.base import Backend
from rate_limiter.backends.memory import InMemoryBackend
from rate_limiter.backends.redis import RedisBackend
from rate_limiter.exceptions import BackendError, RateLimitExceeded
from rate_limiter.types import BackendConfig, RateLimitConfig, RateLimitResult

logger = logging.getLogger(__name__)


class RateLimiter:
    """Production-ready rate limiter with automatic fallback.

    Provides distributed rate limiting with Redis as primary backend and
    in-memory storage as fallback for graceful degradation. Automatically
    switches to fallback backend if primary fails.

    Example:
        >>> limiter = RateLimiter()
        >>> await limiter.check("user:123", rate=100, period=60)
        >>> # Returns RateLimitResult
    """

    def __init__(
        self,
        backend: Backend | None = None,
        fallback_backend: Backend | None = None,
        redis_config: BackendConfig | None = None,
        algorithm: str = "token_bucket",
        auto_fallback: bool = True,
        raise_on_exceeded: bool = False,
    ) -> None:
        """Initialize rate limiter.

        Args:
            backend: Primary backend (defaults to RedisBackend)
            fallback_backend: Fallback backend (defaults to InMemoryBackend)
            redis_config: Configuration for Redis backend
            algorithm: Algorithm to use ('token_bucket' or 'sliding_window')
            auto_fallback: Automatically fallback to memory backend on Redis failure
            raise_on_exceeded: Raise RateLimitExceeded instead of returning result
        """
        self._algorithm = algorithm
        self._auto_fallback = auto_fallback
        self._raise_on_exceeded = raise_on_exceeded
        self._using_fallback = False

        # Initialize backends
        if backend is None:
            self._primary_backend: Backend = RedisBackend(
                config=redis_config, algorithm=algorithm
            )
        else:
            self._primary_backend = backend

        if fallback_backend is None:
            self._fallback_backend: Backend | None = InMemoryBackend()
        else:
            self._fallback_backend = fallback_backend

    async def check(
        self,
        key: str,
        rate: int,
        period: float,
        raise_on_exceeded: bool | None = None,
    ) -> RateLimitResult:
        """Check if request is allowed under rate limit.

        Args:
            key: Unique identifier for rate limit (e.g., user_id, ip_address)
            rate: Maximum number of requests allowed
            period: Time window in seconds
            raise_on_exceeded: Override instance setting for raising exceptions

        Returns:
            RateLimitResult with decision and metadata

        Raises:
            RateLimitExceeded: If rate limit exceeded and raise_on_exceeded is True
            BackendError: If both primary and fallback backends fail
        """
        config = RateLimitConfig(rate=rate, period=period, key=key)
        should_raise = (
            raise_on_exceeded if raise_on_exceeded is not None else self._raise_on_exceeded
        )

        # Try primary backend first
        try:
            result = await self._primary_backend.check_rate_limit(config)
            self._using_fallback = False
        except BackendError as e:
            if not self._auto_fallback or self._fallback_backend is None:
                raise

            logger.warning(f"Primary backend failed, using fallback: {e}")
            self._using_fallback = True

            try:
                result = await self._fallback_backend.check_rate_limit(config)
            except BackendError as fallback_error:
                logger.error(f"Fallback backend also failed: {fallback_error}")
                raise BackendError("Both primary and fallback backends failed") from e

        # Raise exception if configured and limit exceeded
        if should_raise and not result.allowed:
            raise RateLimitExceeded(
                f"Rate limit exceeded for key: {key}", retry_after=result.retry_after
            )

        return result

    async def allow(self, key: str, rate: int, period: float) -> bool:
        """Simplified check that returns only boolean result.

        Args:
            key: Unique identifier for rate limit
            rate: Maximum number of requests allowed
            period: Time window in seconds

        Returns:
            True if request is allowed, False otherwise
        """
        result = await self.check(key, rate, period, raise_on_exceeded=False)
        return result.allowed

    async def reset(self, key: str) -> None:
        """Reset rate limit for a specific key.

        Args:
            key: The rate limit key to reset

        Raises:
            BackendError: If reset operation fails
        """
        try:
            await self._primary_backend.reset(key)
        except BackendError as e:
            if self._auto_fallback and self._fallback_backend:
                logger.warning(f"Primary backend reset failed, using fallback: {e}")
                await self._fallback_backend.reset(key)
            else:
                raise

    async def get_usage(self, key: str) -> int:
        """Get current usage count for a key.

        Args:
            key: The rate limit key

        Returns:
            Current usage count
        """
        try:
            return await self._primary_backend.get_usage(key)
        except BackendError as e:
            if self._auto_fallback and self._fallback_backend:
                logger.warning(f"Primary backend get_usage failed, using fallback: {e}")
                return await self._fallback_backend.get_usage(key)
            raise

    async def health_check(self) -> dict[str, bool]:
        """Check health of all backends.

        Returns:
            Dictionary with health status of each backend
        """
        primary_healthy = await self._primary_backend.health_check()
        fallback_healthy = (
            await self._fallback_backend.health_check() if self._fallback_backend else False
        )

        return {
            "primary": primary_healthy,
            "fallback": fallback_healthy,
            "using_fallback": self._using_fallback,
        }

    async def close(self) -> None:
        """Close all backend connections."""
        await self._primary_backend.close()
        if self._fallback_backend:
            await self._fallback_backend.close()

    async def __aenter__(self) -> "RateLimiter":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    @property
    def is_using_fallback(self) -> bool:
        """Check if currently using fallback backend."""
        return self._using_fallback
