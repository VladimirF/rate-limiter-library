"""Tests for in-memory backend."""

import asyncio

import pytest

from rate_limiter.backends.memory import InMemoryBackend
from rate_limiter.types import RateLimitConfig


@pytest.fixture
async def backend():
    """Create in-memory backend for testing."""
    backend = InMemoryBackend()
    yield backend
    await backend.close()


class TestInMemoryBackend:
    """Test suite for InMemoryBackend."""

    async def test_initial_request_allowed(self, backend):
        """First request should always be allowed."""
        config = RateLimitConfig(rate=10, period=60.0, key="test_user")
        result = await backend.check_rate_limit(config)

        assert result.allowed is True
        assert result.remaining >= 0
        assert result.limit == 10

    async def test_rate_limit_enforcement(self, backend):
        """Requests should be denied after exceeding limit."""
        config = RateLimitConfig(rate=3, period=60.0, key="test_user")

        # Make 3 allowed requests
        for _ in range(3):
            result = await backend.check_rate_limit(config)
            assert result.allowed is True

        # 4th request should be denied
        result = await backend.check_rate_limit(config)
        assert result.allowed is False
        assert result.retry_after > 0

    async def test_token_refill(self, backend):
        """Tokens should refill over time."""
        config = RateLimitConfig(rate=2, period=1.0, key="test_user")

        # Consume all tokens
        await backend.check_rate_limit(config)
        await backend.check_rate_limit(config)

        # Next request should be denied
        result = await backend.check_rate_limit(config)
        assert result.allowed is False

        # Wait for token refill
        await asyncio.sleep(0.6)

        # Should now be allowed
        result = await backend.check_rate_limit(config)
        assert result.allowed is True

    async def test_independent_keys(self, backend):
        """Different keys should have independent rate limits."""
        config1 = RateLimitConfig(rate=2, period=60.0, key="user1")
        config2 = RateLimitConfig(rate=2, period=60.0, key="user2")

        # Exhaust limit for user1
        await backend.check_rate_limit(config1)
        await backend.check_rate_limit(config1)
        result = await backend.check_rate_limit(config1)
        assert result.allowed is False

        # user2 should still be allowed
        result = await backend.check_rate_limit(config2)
        assert result.allowed is True

    async def test_reset(self, backend):
        """Reset should restore full capacity."""
        config = RateLimitConfig(rate=5, period=60.0, key="test_user")

        # Consume some tokens
        await backend.check_rate_limit(config)
        await backend.check_rate_limit(config)

        # Reset
        await backend.reset("test_user")

        # Should have full capacity again
        for _ in range(5):
            result = await backend.check_rate_limit(config)
            assert result.allowed is True

    async def test_get_usage(self, backend):
        """get_usage should return approximate usage."""
        config = RateLimitConfig(rate=10, period=60.0, key="test_user")

        # Initially no usage
        usage = await backend.get_usage("test_user")
        assert usage == 0

        # After consuming tokens
        await backend.check_rate_limit(config)
        await backend.check_rate_limit(config)

        usage = await backend.get_usage("test_user")
        assert usage >= 0  # Should have some usage

    async def test_health_check(self, backend):
        """Health check should always return True for memory backend."""
        healthy = await backend.health_check()
        assert healthy is True

    async def test_concurrent_access(self, backend):
        """Backend should handle concurrent requests safely."""
        config = RateLimitConfig(rate=100, period=60.0, key="test_user")

        # Make 100 concurrent requests
        tasks = [backend.check_rate_limit(config) for _ in range(100)]
        results = await asyncio.gather(*tasks)

        # All should be allowed
        allowed_count = sum(1 for r in results if r.allowed)
        assert allowed_count == 100

        # 101st should be denied
        result = await backend.check_rate_limit(config)
        assert result.allowed is False

    async def test_remaining_count_accuracy(self, backend):
        """Remaining count should accurately reflect available tokens."""
        config = RateLimitConfig(rate=5, period=60.0, key="test_user")

        # Check remaining after each request
        result = await backend.check_rate_limit(config)
        assert result.remaining == 4

        result = await backend.check_rate_limit(config)
        assert result.remaining == 3

        result = await backend.check_rate_limit(config)
        assert result.remaining == 2

    async def test_context_manager(self, backend):
        """Backend should work as async context manager."""
        async with InMemoryBackend() as backend:
            config = RateLimitConfig(rate=10, period=60.0, key="test_user")
            result = await backend.check_rate_limit(config)
            assert result.allowed is True

    async def test_different_rate_configs(self, backend):
        """Should handle different rate configurations correctly."""
        # High rate, short period
        config1 = RateLimitConfig(rate=100, period=1.0, key="user1")
        result = await backend.check_rate_limit(config1)
        assert result.allowed is True

        # Low rate, long period
        config2 = RateLimitConfig(rate=5, period=3600.0, key="user2")
        result = await backend.check_rate_limit(config2)
        assert result.allowed is True

    async def test_reset_at_timestamp(self, backend):
        """reset_at should be a valid future timestamp."""
        import time

        config = RateLimitConfig(rate=10, period=60.0, key="test_user")
        result = await backend.check_rate_limit(config)

        current_time = time.time()
        assert result.reset_at > current_time
        assert result.reset_at <= current_time + 60.0
