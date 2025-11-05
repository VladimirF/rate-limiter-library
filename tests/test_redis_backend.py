"""Tests for Redis backend.

These tests use testcontainers to spin up a real Redis instance in Docker.
This ensures tests run against actual Redis, not mocks or in-memory alternatives.
"""

import asyncio

import pytest

from rate_limiter.backends.redis import RedisBackend
from rate_limiter.exceptions import BackendError
from rate_limiter.types import BackendConfig, RateLimitConfig


@pytest.fixture
async def redis_backend(redis_container):
    """Create Redis backend for testing with actual Redis container."""
    config = BackendConfig(
        host=redis_container["host"],
        port=redis_container["port"],
        db=0,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    backend = RedisBackend(config=config, algorithm="token_bucket")

    yield backend
    await backend.close()


@pytest.fixture
async def sliding_window_backend(redis_container):
    """Create Redis backend with sliding window algorithm."""
    config = BackendConfig(
        host=redis_container["host"],
        port=redis_container["port"],
        db=0,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    backend = RedisBackend(config=config, algorithm="sliding_window")

    yield backend
    await backend.close()


class TestRedisBackendTokenBucket:
    """Test suite for RedisBackend with token bucket algorithm."""

    async def test_initial_request_allowed(self, redis_backend):
        """First request should be allowed."""
        config = RateLimitConfig(rate=10, period=60.0, key="redis_test_user_1")

        # Clean up from previous tests
        await redis_backend.reset(config.key)

        result = await redis_backend.check_rate_limit(config)
        assert result.allowed is True
        assert result.remaining >= 0
        assert result.limit == 10

    async def test_rate_limit_enforcement(self, redis_backend):
        """Requests should be denied after exceeding limit."""
        config = RateLimitConfig(rate=3, period=60.0, key="redis_test_user_2")
        await redis_backend.reset(config.key)

        # Make 3 allowed requests
        for _ in range(3):
            result = await redis_backend.check_rate_limit(config)
            assert result.allowed is True

        # 4th request should be denied
        result = await redis_backend.check_rate_limit(config)
        assert result.allowed is False
        assert result.retry_after > 0

    async def test_token_refill(self, redis_backend):
        """Tokens should refill over time."""
        config = RateLimitConfig(rate=2, period=1.0, key="redis_test_user_3")
        await redis_backend.reset(config.key)

        # Consume all tokens
        await redis_backend.check_rate_limit(config)
        await redis_backend.check_rate_limit(config)

        # Next request should be denied
        result = await redis_backend.check_rate_limit(config)
        assert result.allowed is False

        # Wait for token refill
        await asyncio.sleep(0.6)

        # Should now be allowed
        result = await redis_backend.check_rate_limit(config)
        assert result.allowed is True

    async def test_independent_keys(self, redis_backend):
        """Different keys should have independent rate limits."""
        config1 = RateLimitConfig(rate=2, period=60.0, key="redis_user_a")
        config2 = RateLimitConfig(rate=2, period=60.0, key="redis_user_b")

        await redis_backend.reset(config1.key)
        await redis_backend.reset(config2.key)

        # Exhaust limit for user1
        await redis_backend.check_rate_limit(config1)
        await redis_backend.check_rate_limit(config1)
        result = await redis_backend.check_rate_limit(config1)
        assert result.allowed is False

        # user2 should still be allowed
        result = await redis_backend.check_rate_limit(config2)
        assert result.allowed is True

    async def test_reset(self, redis_backend):
        """Reset should restore full capacity."""
        config = RateLimitConfig(rate=5, period=60.0, key="redis_test_user_4")
        await redis_backend.reset(config.key)

        # Consume some tokens
        await redis_backend.check_rate_limit(config)
        await redis_backend.check_rate_limit(config)

        # Reset
        await redis_backend.reset(config.key)

        # Should have full capacity again
        for _ in range(5):
            result = await redis_backend.check_rate_limit(config)
            assert result.allowed is True

    async def test_health_check_success(self, redis_backend):
        """Health check should return True when Redis is available."""
        healthy = await redis_backend.health_check()
        assert healthy is True

    async def test_concurrent_access(self, redis_backend):
        """Backend should handle concurrent requests atomically."""
        config = RateLimitConfig(rate=50, period=60.0, key="redis_concurrent_test")
        await redis_backend.reset(config.key)

        # Make 50 concurrent requests
        tasks = [redis_backend.check_rate_limit(config) for _ in range(50)]
        results = await asyncio.gather(*tasks)

        # All should be allowed
        allowed_count = sum(1 for r in results if r.allowed)
        assert allowed_count == 50

        # 51st should be denied
        result = await redis_backend.check_rate_limit(config)
        assert result.allowed is False

    async def test_distributed_rate_limiting(self, redis_backend, redis_container):
        """Multiple backend instances should share rate limit state."""
        config = RateLimitConfig(rate=5, period=60.0, key="redis_distributed_test")

        # Create two backend instances pointing to same Redis
        backend1 = redis_backend
        backend2 = RedisBackend(
            config=BackendConfig(
                host=redis_container["host"],
                port=redis_container["port"],
                db=0,
                socket_timeout=5.0,
            ),
            algorithm="token_bucket",
        )

        try:
            await backend1.reset(config.key)

            # Use tokens across both backends
            await backend1.check_rate_limit(config)
            await backend1.check_rate_limit(config)
            await backend2.check_rate_limit(config)
            await backend2.check_rate_limit(config)
            await backend1.check_rate_limit(config)

            # Next request on either backend should be denied
            result = await backend2.check_rate_limit(config)
            assert result.allowed is False

        finally:
            await backend2.close()


class TestRedisBackendSlidingWindow:
    """Test suite for RedisBackend with sliding window algorithm."""

    async def test_sliding_window_basic(self, sliding_window_backend):
        """Sliding window should enforce rate limits."""
        config = RateLimitConfig(rate=5, period=2.0, key="sliding_test_1")
        await sliding_window_backend.reset(config.key)

        # Make 5 requests
        for _ in range(5):
            result = await sliding_window_backend.check_rate_limit(config)
            assert result.allowed is True

        # 6th should be denied
        result = await sliding_window_backend.check_rate_limit(config)
        assert result.allowed is False

    async def test_sliding_window_reset(self, sliding_window_backend):
        """Window should reset after period expires."""
        config = RateLimitConfig(rate=3, period=1.0, key="sliding_test_2")
        await sliding_window_backend.reset(config.key)

        # Exhaust limit
        for _ in range(3):
            await sliding_window_backend.check_rate_limit(config)

        # Should be denied
        result = await sliding_window_backend.check_rate_limit(config)
        assert result.allowed is False

        # Wait for window to expire
        await asyncio.sleep(1.1)

        # Should be allowed again
        result = await sliding_window_backend.check_rate_limit(config)
        assert result.allowed is True

    async def test_sliding_window_concurrent(self, sliding_window_backend):
        """Sliding window should handle concurrent requests."""
        config = RateLimitConfig(rate=20, period=5.0, key="sliding_concurrent")
        await sliding_window_backend.reset(config.key)

        tasks = [sliding_window_backend.check_rate_limit(config) for _ in range(20)]
        results = await asyncio.gather(*tasks)

        allowed_count = sum(1 for r in results if r.allowed)
        assert allowed_count == 20


class TestRedisBackendErrors:
    """Test error handling in Redis backend."""

    async def test_connection_failure(self):
        """Should raise BackendError on connection failure."""
        config = BackendConfig(host="invalid_host", port=9999, socket_connect_timeout=0.1)
        backend = RedisBackend(config=config)

        rate_config = RateLimitConfig(rate=10, period=60.0, key="test")

        with pytest.raises(BackendError):
            await backend.check_rate_limit(rate_config)

        await backend.close()

    async def test_health_check_failure(self):
        """Health check should return False for invalid connection."""
        config = BackendConfig(
            host="invalid_host", port=9999, socket_connect_timeout=0.1, socket_timeout=0.1
        )
        backend = RedisBackend(config=config)

        healthy = await backend.health_check()
        assert healthy is False

        await backend.close()


class TestRedisBackendConfiguration:
    """Test Redis backend configuration."""

    async def test_custom_redis_client(self, redis_client):
        """Should accept custom Redis client."""
        backend = RedisBackend(redis_client=redis_client)

        # Should use provided client
        config = RateLimitConfig(rate=10, period=60.0, key="custom_client_test")
        result = await backend.check_rate_limit(config)
        assert result is not None

        # Closing backend should not close external client
        await backend.close()

        # Client should still work
        await redis_client.ping()

    async def test_algorithm_validation(self):
        """Should validate algorithm parameter."""
        with pytest.raises(ValueError, match="Unknown algorithm"):
            RedisBackend(algorithm="invalid_algorithm")
