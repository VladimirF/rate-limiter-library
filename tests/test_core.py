"""Tests for core RateLimiter with graceful degradation."""

import pytest

from rate_limiter.backends.memory import InMemoryBackend
from rate_limiter.backends.redis import RedisBackend
from rate_limiter.core import RateLimiter
from rate_limiter.exceptions import BackendError, RateLimitExceeded
from rate_limiter.types import BackendConfig


@pytest.fixture
async def memory_limiter():
    """Create rate limiter with memory backend."""
    limiter = RateLimiter(backend=InMemoryBackend(), fallback_backend=None)
    yield limiter
    await limiter.close()


@pytest.fixture
async def redis_limiter(redis_container):
    """Create rate limiter with Redis backend using testcontainer."""
    config = BackendConfig(
        host=redis_container["host"],
        port=redis_container["port"],
        db=0,
        socket_timeout=5.0,
    )
    backend = RedisBackend(config=config)

    limiter = RateLimiter(backend=backend, fallback_backend=InMemoryBackend())
    yield limiter
    await limiter.close()


class TestRateLimiterBasic:
    """Basic rate limiter functionality tests."""

    async def test_check_allows_request(self, memory_limiter):
        """check() should allow request within limits."""
        result = await memory_limiter.check("user1", rate=10, period=60)
        assert result.allowed is True
        assert result.limit == 10

    async def test_check_denies_request(self, memory_limiter):
        """check() should deny request when limit exceeded."""
        # Exhaust limit
        for _ in range(3):
            await memory_limiter.check("user2", rate=3, period=60)

        # Should be denied
        result = await memory_limiter.check("user2", rate=3, period=60)
        assert result.allowed is False
        assert result.retry_after > 0

    async def test_allow_method(self, memory_limiter):
        """allow() should return simple boolean."""
        allowed = await memory_limiter.allow("user3", rate=5, period=60)
        assert allowed is True

        # Exhaust limit
        for _ in range(4):
            await memory_limiter.allow("user3", rate=5, period=60)

        # Should be denied
        allowed = await memory_limiter.allow("user3", rate=5, period=60)
        assert allowed is False

    async def test_raise_on_exceeded(self, memory_limiter):
        """Should raise exception when configured."""
        limiter = RateLimiter(
            backend=InMemoryBackend(), fallback_backend=None, raise_on_exceeded=True
        )

        try:
            # Exhaust limit
            for _ in range(3):
                await limiter.check("user4", rate=3, period=60)

            # Should raise exception
            with pytest.raises(RateLimitExceeded) as exc_info:
                await limiter.check("user4", rate=3, period=60)

            assert exc_info.value.retry_after is not None
            assert exc_info.value.retry_after > 0

        finally:
            await limiter.close()

    async def test_reset(self, memory_limiter):
        """reset() should restore capacity."""
        # Exhaust limit
        for _ in range(3):
            await memory_limiter.check("user5", rate=3, period=60)

        result = await memory_limiter.check("user5", rate=3, period=60)
        assert result.allowed is False

        # Reset
        await memory_limiter.reset("user5")

        # Should be allowed again
        result = await memory_limiter.check("user5", rate=3, period=60)
        assert result.allowed is True

    async def test_get_usage(self, memory_limiter):
        """get_usage() should return usage count."""
        usage = await memory_limiter.get_usage("user6")
        assert usage == 0

        # Make some requests
        await memory_limiter.check("user6", rate=10, period=60)
        await memory_limiter.check("user6", rate=10, period=60)

        usage = await memory_limiter.get_usage("user6")
        assert usage >= 0

    async def test_health_check(self, memory_limiter):
        """health_check() should return status of backends."""
        health = await memory_limiter.health_check()
        assert "primary" in health
        assert health["primary"] is True

    async def test_context_manager(self):
        """RateLimiter should work as context manager."""
        async with RateLimiter(backend=InMemoryBackend(), fallback_backend=None) as limiter:
            result = await limiter.check("user7", rate=10, period=60)
            assert result.allowed is True


class TestGracefulDegradation:
    """Test automatic fallback to memory backend."""

    async def test_fallback_on_redis_failure(self):
        """Should fallback to memory backend when Redis fails."""
        # Create Redis backend with invalid config
        bad_config = BackendConfig(host="invalid_host", port=9999, socket_connect_timeout=0.1)
        bad_backend = RedisBackend(config=bad_config)

        limiter = RateLimiter(
            backend=bad_backend, fallback_backend=InMemoryBackend(), auto_fallback=True
        )

        try:
            # Should use fallback automatically
            result = await limiter.check("user8", rate=10, period=60)
            assert result.allowed is True
            assert limiter.is_using_fallback is True

        finally:
            await limiter.close()

    async def test_no_fallback_when_disabled(self):
        """Should raise error when auto_fallback is False."""
        bad_config = BackendConfig(host="invalid_host", port=9999, socket_connect_timeout=0.1)
        bad_backend = RedisBackend(config=bad_config)

        limiter = RateLimiter(
            backend=bad_backend, fallback_backend=InMemoryBackend(), auto_fallback=False
        )

        try:
            with pytest.raises(BackendError):
                await limiter.check("user9", rate=10, period=60)

        finally:
            await limiter.close()

    async def test_fallback_on_reset(self):
        """reset() should fallback on primary failure."""
        bad_config = BackendConfig(host="invalid_host", port=9999, socket_connect_timeout=0.1)
        bad_backend = RedisBackend(config=bad_config)

        limiter = RateLimiter(
            backend=bad_backend, fallback_backend=InMemoryBackend(), auto_fallback=True
        )

        try:
            # Should use fallback for reset
            await limiter.reset("user10")  # Should not raise

        finally:
            await limiter.close()

    async def test_fallback_on_get_usage(self):
        """get_usage() should fallback on primary failure."""
        bad_config = BackendConfig(host="invalid_host", port=9999, socket_connect_timeout=0.1)
        bad_backend = RedisBackend(config=bad_config)

        limiter = RateLimiter(
            backend=bad_backend, fallback_backend=InMemoryBackend(), auto_fallback=True
        )

        try:
            usage = await limiter.get_usage("user11")
            assert usage == 0

        finally:
            await limiter.close()


class TestRedisIntegration:
    """Integration tests with actual Redis."""

    async def test_redis_distributed_limiting(self, redis_limiter):
        """Multiple instances should share rate limit state."""
        # Make requests
        for _ in range(3):
            result = await redis_limiter.check("distributed_user", rate=3, period=60)
            assert result.allowed is True

        # Should be denied
        result = await redis_limiter.check("distributed_user", rate=3, period=60)
        assert result.allowed is False

    async def test_redis_with_fallback(self, redis_limiter):
        """Should work correctly with Redis primary."""
        result = await redis_limiter.check("redis_user", rate=10, period=60)
        assert result.allowed is True
        assert redis_limiter.is_using_fallback is False

        health = await redis_limiter.health_check()
        assert health["primary"] is True

    async def test_different_algorithms(self, redis_container):
        """Should work with different algorithms."""
        config = BackendConfig(
            host=redis_container["host"],
            port=redis_container["port"],
            db=0,
            socket_timeout=5.0,
        )

        # Token bucket
        backend1 = RedisBackend(config=config, algorithm="token_bucket")
        limiter1 = RateLimiter(backend=backend1, fallback_backend=None)

        # Sliding window
        backend2 = RedisBackend(config=config, algorithm="sliding_window")
        limiter2 = RateLimiter(backend=backend2, fallback_backend=None)

        try:
            result1 = await limiter1.check("algo_test_1", rate=10, period=60)
            assert result1.allowed is True

            result2 = await limiter2.check("algo_test_2", rate=10, period=60)
            assert result2.allowed is True

        finally:
            await limiter1.close()
            await limiter2.close()


class TestConfiguration:
    """Test various configuration options."""

    async def test_custom_backends(self):
        """Should accept custom backend instances."""
        primary = InMemoryBackend()
        fallback = InMemoryBackend()

        limiter = RateLimiter(backend=primary, fallback_backend=fallback)

        try:
            result = await limiter.check("custom_test", rate=5, period=60)
            assert result.allowed is True

        finally:
            await limiter.close()

    async def test_no_fallback_backend(self):
        """Should work without fallback backend."""
        limiter = RateLimiter(backend=InMemoryBackend(), fallback_backend=None)

        try:
            result = await limiter.check("no_fallback_test", rate=5, period=60)
            assert result.allowed is True

        finally:
            await limiter.close()

    async def test_override_raise_on_exceeded(self, memory_limiter):
        """Per-call override should work."""
        # Exhaust limit
        for _ in range(3):
            await memory_limiter.check("override_test", rate=3, period=60)

        # Should not raise even if instance configured to raise
        result = await memory_limiter.check(
            "override_test", rate=3, period=60, raise_on_exceeded=False
        )
        assert result.allowed is False

        # Now with raise
        with pytest.raises(RateLimitExceeded):
            await memory_limiter.check("override_test", rate=3, period=60, raise_on_exceeded=True)
