"""In-memory backend for rate limiting - used for fallback and testing."""

import asyncio
import time
from collections import defaultdict

from rate_limiter.backends.base import BaseBackend
from rate_limiter.types import RateLimitConfig, RateLimitResult


class InMemoryBackend(BaseBackend):
    """Thread-safe in-memory rate limiter backend.

    Uses token bucket algorithm with asyncio locks for thread safety.
    Suitable for single-instance deployments, testing, and fallback when Redis is unavailable.

    Note: This backend does not share state across processes/servers.
    For true distributed rate limiting, use RedisBackend.
    """

    def __init__(self) -> None:
        """Initialize in-memory backend with tracking structures."""
        self._buckets: defaultdict[str, dict[str, float]] = defaultdict(
            lambda: {"tokens": 0.0, "last_update": time.time()}
        )
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._limits: dict[str, tuple[int, float]] = {}

    async def check_rate_limit(self, config: RateLimitConfig) -> RateLimitResult:
        """Check rate limit using token bucket algorithm.

        The token bucket refills at a constant rate. Each request consumes one token.
        If no tokens are available, the request is denied.

        Args:
            config: Rate limit configuration

        Returns:
            RateLimitResult with decision and metadata
        """
        async with self._locks[config.key]:
            return await self._check_and_update_bucket(config)

    async def _check_and_update_bucket(self, config: RateLimitConfig) -> RateLimitResult:
        """Internal method to check and update token bucket state."""
        current_time = time.time()
        bucket = self._buckets[config.key]

        # Initialize bucket with full capacity on first access
        is_first_access = config.key not in self._limits

        # Store limit configuration for this key
        self._limits[config.key] = (config.rate, config.period)

        # Calculate refill rate (tokens per second)
        refill_rate = config.rate / config.period

        if is_first_access:
            # First access: start with full capacity
            bucket["tokens"] = float(config.rate)
            bucket["last_update"] = current_time
        else:
            # Calculate tokens to add since last update
            time_passed = current_time - bucket["last_update"]
            new_tokens = time_passed * refill_rate

            # Update token count (capped at max capacity)
            bucket["tokens"] = min(config.rate, bucket["tokens"] + new_tokens)
            bucket["last_update"] = current_time

        # Check if request can be allowed
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            remaining = int(bucket["tokens"])

            # Calculate when bucket will be full again
            tokens_to_full = config.rate - bucket["tokens"]
            time_to_full = tokens_to_full / refill_rate
            reset_at = current_time + time_to_full

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=config.rate,
                retry_after=0.0,
                reset_at=reset_at,
            )
        else:
            # Calculate when next token will be available
            tokens_needed = 1.0 - bucket["tokens"]
            retry_after = tokens_needed / refill_rate

            # Calculate reset time (when bucket is full)
            tokens_to_full = config.rate - bucket["tokens"]
            time_to_full = tokens_to_full / refill_rate
            reset_at = current_time + time_to_full

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=config.rate,
                retry_after=retry_after,
                reset_at=reset_at,
            )

    async def reset(self, key: str) -> None:
        """Reset rate limit for a specific key.

        Args:
            key: The rate limit key to reset
        """
        async with self._locks[key]:
            if key in self._buckets:
                # Reset to full capacity if we know the limit
                if key in self._limits:
                    rate, _ = self._limits[key]
                    self._buckets[key] = {"tokens": float(rate), "last_update": time.time()}
                else:
                    del self._buckets[key]

    async def get_usage(self, key: str) -> int:
        """Get current usage (consumed tokens) for a key.

        Args:
            key: The rate limit key

        Returns:
            Number of tokens consumed (rate - remaining tokens)
        """
        async with self._locks[key]:
            if key not in self._buckets or key not in self._limits:
                return 0

            rate, period = self._limits[key]
            bucket = self._buckets[key]

            # Recalculate current tokens
            current_time = time.time()
            time_passed = current_time - bucket["last_update"]
            refill_rate = rate / period
            new_tokens = time_passed * refill_rate
            current_tokens = min(rate, bucket["tokens"] + new_tokens)

            return int(rate - current_tokens)

    async def close(self) -> None:
        """Close backend and cleanup resources."""
        self._buckets.clear()
        self._locks.clear()
        self._limits.clear()

    async def health_check(self) -> bool:
        """Check backend health.

        Returns:
            Always True for in-memory backend (it's always available)
        """
        return True
