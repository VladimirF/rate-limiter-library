"""Pytest configuration and shared fixtures."""

import asyncio
import os

import pytest

# Check if Docker is available for integration tests
DOCKER_AVAILABLE = os.environ.get("REDIS_HOST") is None


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def redis_container():
    """
    Provide Redis container for integration tests using testcontainers.

    This automatically:
    - Pulls Redis Docker image if needed
    - Starts Redis container
    - Provides connection details
    - Cleans up after tests
    """
    if not DOCKER_AVAILABLE:
        # Use existing Redis from environment
        redis_host = os.environ.get("REDIS_HOST", "localhost")
        redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        yield {"host": redis_host, "port": redis_port}
        return

    try:
        from testcontainers.redis import RedisContainer
    except ImportError:
        pytest.skip(
            "testcontainers not available - install with: pip install testcontainers[redis]"
        )
        return

    # Start Redis container
    with RedisContainer("redis:7-alpine") as redis:
        yield {
            "host": redis.get_container_host_ip(),
            "port": redis.get_exposed_port(6379),
        }


@pytest.fixture
async def redis_client(redis_container):
    """Provide async Redis client connected to test container."""
    import redis.asyncio as aioredis

    client = await aioredis.from_url(
        f"redis://{redis_container['host']}:{redis_container['port']}/0",
        socket_timeout=5.0,
        decode_responses=True,
    )

    yield client

    # Cleanup: flush test database
    try:
        await client.flushdb()
    except Exception:
        pass
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
async def cleanup_redis_keys(redis_container):
    """Cleanup Redis keys after each test."""
    yield

    # Cleanup after test
    try:
        import redis.asyncio as aioredis

        client = await aioredis.from_url(
            f"redis://{redis_container['host']}:{redis_container['port']}/0",
            socket_timeout=1.0,
        )
        try:
            # Delete all ratelimit keys
            async for key in client.scan_iter("ratelimit:*"):
                await client.delete(key)
        finally:
            await client.aclose()
    except Exception:
        pass  # Ignore cleanup errors
