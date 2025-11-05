"""Pytest configuration and shared fixtures."""

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def cleanup_redis():
    """Cleanup Redis test database after each test."""
    yield

    # Try to clean up test keys (don't fail if Redis unavailable)
    try:
        import redis.asyncio as aioredis

        client = await aioredis.from_url("redis://localhost:6379/15", socket_timeout=0.5)
        try:
            # Delete all test keys
            async for key in client.scan_iter("ratelimit:*"):
                await client.delete(key)
        finally:
            await client.aclose()
    except Exception:
        pass  # Redis not available, skip cleanup
