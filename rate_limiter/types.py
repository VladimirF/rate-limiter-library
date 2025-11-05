"""Type definitions for rate limiter."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RateLimitResult:
    """Result of a rate limit check.

    Attributes:
        allowed: Whether the request is allowed
        remaining: Number of tokens/requests remaining in the current window
        limit: Maximum number of tokens/requests allowed
        retry_after: Seconds until the next token is available (if not allowed)
        reset_at: Unix timestamp when the rate limit resets
    """

    allowed: bool
    remaining: int
    limit: int
    retry_after: float
    reset_at: float


@dataclass(frozen=True)
class RateLimitConfig:
    """Configuration for rate limiting.

    Attributes:
        rate: Number of requests allowed
        period: Time period in seconds
        key: Unique identifier for the rate limit (e.g., user_id, ip_address)
    """

    rate: int
    period: float
    key: str

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("rate must be positive")
        if self.period <= 0:
            raise ValueError("period must be positive")
        if not self.key:
            raise ValueError("key cannot be empty")


@dataclass
class BackendConfig:
    """Configuration for backend storage."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    socket_timeout: float = 1.0
    socket_connect_timeout: float = 1.0
    max_connections: int = 50
    decode_responses: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Redis client initialization."""
        return {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "password": self.password,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
            "max_connections": self.max_connections,
            "decode_responses": self.decode_responses,
        }
