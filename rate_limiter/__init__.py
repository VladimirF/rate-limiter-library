"""
Distributed Rate Limiter - A high-performance rate limiting library.

Provides distributed rate limiting with multiple algorithms (token bucket, sliding window)
and backends (Redis, in-memory) with graceful degradation.
"""

from rate_limiter.core import RateLimiter
from rate_limiter.decorators import rate_limit
from rate_limiter.exceptions import RateLimiterError, RateLimitExceeded

__version__ = "0.1.0"
__all__ = [
    "RateLimiter",
    "rate_limit",
    "RateLimitExceeded",
    "RateLimiterError",
]
