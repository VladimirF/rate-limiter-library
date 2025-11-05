"""Redis backend for distributed rate limiting."""

import time
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from rate_limiter.backends.base import BaseBackend
from rate_limiter.exceptions import BackendError
from rate_limiter.types import BackendConfig, RateLimitConfig, RateLimitResult

if TYPE_CHECKING:
    from redis.asyncio.client import Redis as RedisType
else:
    RedisType = Redis


# Lua script for token bucket algorithm
# This runs atomically on Redis server, preventing race conditions
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local period = tonumber(ARGV[2])
local current_time = tonumber(ARGV[3])

-- Get current bucket state
local bucket = redis.call('HMGET', key, 'tokens', 'last_update')
local tokens = tonumber(bucket[1])
local last_update = tonumber(bucket[2])

-- Initialize bucket if it doesn't exist
if not tokens then
    tokens = rate
    last_update = current_time
end

-- Calculate token refill
local time_passed = current_time - last_update
local refill_rate = rate / period
local new_tokens = time_passed * refill_rate
tokens = math.min(rate, tokens + new_tokens)

-- Check if request can be allowed
local allowed = 0
local remaining = 0
local retry_after = 0

if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
    remaining = math.floor(tokens)
else
    -- Calculate wait time for next token
    retry_after = (1 - tokens) / refill_rate
end

-- Update bucket state
redis.call('HMSET', key, 'tokens', tokens, 'last_update', current_time)
redis.call('EXPIRE', key, math.ceil(period * 2))  -- Expire after 2 periods of inactivity

-- Calculate reset time
local tokens_to_full = rate - tokens
local time_to_full = tokens_to_full / refill_rate
local reset_at = current_time + time_to_full

return {allowed, remaining, rate, retry_after, reset_at}
"""


# Lua script for sliding window counter algorithm
# More memory efficient for high-rate scenarios
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local period = tonumber(ARGV[2])
local current_time = tonumber(ARGV[3])

-- Use sorted set to track requests with timestamps
local window_start = current_time - period

-- Remove old entries outside the window
redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

-- Count requests in current window
local current_count = redis.call('ZCARD', key)

local allowed = 0
local remaining = 0
local retry_after = 0

if current_count < rate then
    -- Add current request
    redis.call('ZADD', key, current_time, current_time)
    redis.call('EXPIRE', key, math.ceil(period * 2))
    allowed = 1
    remaining = rate - current_count - 1
else
    -- Get oldest request timestamp
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if #oldest > 0 then
        local oldest_time = tonumber(oldest[2])
        retry_after = oldest_time + period - current_time
    else
        retry_after = period
    end
end

local reset_at = current_time + period

return {allowed, remaining, rate, retry_after, reset_at}
"""


class RedisBackend(BaseBackend):
    """High-performance Redis backend for distributed rate limiting.

    Uses Lua scripts for atomic operations, ensuring accurate rate limiting
    even under high concurrency. Supports both token bucket and sliding window algorithms.

    The token bucket algorithm provides smooth rate limiting with token refill,
    while sliding window provides stricter guarantees but uses more memory.
    """

    def __init__(
        self,
        config: BackendConfig | None = None,
        redis_client: "Redis | None" = None,
        algorithm: str = "token_bucket",
    ) -> None:
        """Initialize Redis backend.

        Args:
            config: Backend configuration (host, port, etc.)
            redis_client: Optional pre-configured Redis client
            algorithm: Algorithm to use ('token_bucket' or 'sliding_window')

        Raises:
            ConfigurationError: If configuration is invalid
        """
        self._config = config or BackendConfig()
        self._client = redis_client
        self._algorithm = algorithm
        self._token_bucket_sha: str | None = None
        self._sliding_window_sha: str | None = None
        self._is_external_client = redis_client is not None

        if algorithm not in ("token_bucket", "sliding_window"):
            raise ValueError(f"Unknown algorithm: {algorithm}")

    async def _ensure_connected(self) -> Redis:
        """Ensure Redis client is connected and scripts are loaded."""
        if self._client is None:
            self._client = await aioredis.from_url(
                f"redis://{self._config.host}:{self._config.port}/{self._config.db}",
                password=self._config.password,
                socket_timeout=self._config.socket_timeout,
                socket_connect_timeout=self._config.socket_connect_timeout,
                max_connections=self._config.max_connections,
                decode_responses=True,
            )

        # Load Lua scripts if not already loaded
        if self._token_bucket_sha is None:
            self._token_bucket_sha = await self._client.script_load(TOKEN_BUCKET_SCRIPT)
        if self._sliding_window_sha is None:
            self._sliding_window_sha = await self._client.script_load(SLIDING_WINDOW_SCRIPT)

        return self._client

    async def check_rate_limit(self, config: RateLimitConfig) -> RateLimitResult:
        """Check rate limit using configured algorithm.

        Args:
            config: Rate limit configuration

        Returns:
            RateLimitResult with decision and metadata

        Raises:
            BackendError: If Redis operation fails
        """
        try:
            client = await self._ensure_connected()
            current_time = time.time()

            # Choose script based on algorithm
            if self._algorithm == "token_bucket":
                sha = self._token_bucket_sha
            else:
                sha = self._sliding_window_sha

            # Execute Lua script atomically
            result = await client.evalsha(
                sha,  # type: ignore
                1,  # number of keys
                f"ratelimit:{config.key}",  # key
                config.rate,  # rate limit
                config.period,  # time period
                current_time,  # current timestamp
            )

            # Parse result from Lua script
            allowed, remaining, limit, retry_after, reset_at = result

            return RateLimitResult(
                allowed=bool(allowed),
                remaining=int(remaining),
                limit=int(limit),
                retry_after=float(retry_after),
                reset_at=float(reset_at),
            )

        except RedisError as e:
            raise BackendError(f"Redis operation failed: {e}") from e

    async def reset(self, key: str) -> None:
        """Reset rate limit for a specific key.

        Args:
            key: The rate limit key to reset

        Raises:
            BackendError: If Redis operation fails
        """
        try:
            client = await self._ensure_connected()
            await client.delete(f"ratelimit:{key}")
        except RedisError as e:
            raise BackendError(f"Redis reset failed: {e}") from e

    async def get_usage(self, key: str) -> int:
        """Get current usage for a key.

        Args:
            key: The rate limit key

        Returns:
            Current usage count

        Raises:
            BackendError: If Redis operation fails
        """
        try:
            client = await self._ensure_connected()

            if self._algorithm == "token_bucket":
                # For token bucket, calculate consumed tokens
                bucket = await client.hmget(f"ratelimit:{key}", "tokens", "last_update")
                if bucket[0] is None:
                    return 0

                tokens = float(bucket[0])
                # Usage is implicit in consumed tokens, but we need rate limit config
                # For simplicity, return inverse of remaining tokens
                return int(max(0, 100 - tokens))  # Approximate

            else:
                # For sliding window, count entries in sorted set
                count = await client.zcard(f"ratelimit:{key}")
                return int(count) if count else 0

        except RedisError as e:
            raise BackendError(f"Redis get_usage failed: {e}") from e

    async def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self._client is not None and not self._is_external_client:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        """Check if Redis is accessible.

        Returns:
            True if Redis is healthy, False otherwise
        """
        try:
            client = await self._ensure_connected()
            await client.ping()
            return True
        except (RedisError, OSError):
            return False
