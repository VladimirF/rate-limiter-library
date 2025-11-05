"""Exception classes for rate limiter."""

from typing import Optional


class RateLimiterError(Exception):
    """Base exception for all rate limiter errors."""

    pass


class RateLimitExceeded(RateLimiterError):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BackendError(RateLimiterError):
    """Raised when backend operation fails."""

    pass


class ConfigurationError(RateLimiterError):
    """Raised when configuration is invalid."""

    pass
