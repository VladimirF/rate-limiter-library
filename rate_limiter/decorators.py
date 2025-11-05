"""Decorators for easy rate limiting of functions and methods."""

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

from rate_limiter.core import RateLimiter
from rate_limiter.exceptions import RateLimitExceeded

F = TypeVar("F", bound=Callable[..., Any])


def rate_limit(
    rate: int,
    period: float,
    key_func: Callable[..., str] | None = None,
    limiter: RateLimiter | None = None,
    raise_on_exceeded: bool = True,
) -> Callable[[F], F]:
    """Decorator to rate limit function or method calls.

    Args:
        rate: Maximum number of calls allowed
        period: Time window in seconds
        key_func: Function to extract rate limit key from function arguments.
                  If None, uses a global key for the function.
        limiter: RateLimiter instance to use. If None, creates a new one.
        raise_on_exceeded: Whether to raise RateLimitExceeded or return None

    Example:
        >>> @rate_limit(rate=10, period=60, key_func=lambda user_id: f"user:{user_id}")
        >>> async def api_call(user_id: str):
        >>>     return "data"
        >>>
        >>> # Will be rate limited per user_id
        >>> await api_call("user123")

    Example with global limit:
        >>> @rate_limit(rate=100, period=60)
        >>> async def expensive_operation():
        >>>     return "result"
    """
    _limiter = limiter or RateLimiter()

    def decorator(func: F) -> F:
        # Check if function is async
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Determine rate limit key
                if key_func:
                    key = key_func(*args, **kwargs)
                else:
                    # Use function name as global key
                    key = f"func:{func.__module__}.{func.__qualname__}"

                # Check rate limit
                try:
                    result = await _limiter.check(
                        key=key,
                        rate=rate,
                        period=period,
                        raise_on_exceeded=raise_on_exceeded,
                    )

                    if not result.allowed and not raise_on_exceeded:
                        return None

                    # Call original function if allowed
                    return await func(*args, **kwargs)

                except RateLimitExceeded:
                    if raise_on_exceeded:
                        raise
                    return None

            return cast(F, async_wrapper)

        else:
            # Sync functions not supported for now (would need sync Redis client)
            raise TypeError(
                "rate_limit decorator currently only supports async functions. "
                "Consider making your function async or use the RateLimiter class directly."
            )

    return decorator


def rate_limit_method(
    rate: int,
    period: float,
    key_attr: str = "id",
    key_prefix: str = "",
    limiter: RateLimiter | None = None,
    raise_on_exceeded: bool = True,
) -> Callable[[F], F]:
    """Decorator to rate limit class methods based on instance attributes.

    Useful for rate limiting methods on objects like User, Request, etc.

    Args:
        rate: Maximum number of calls allowed
        period: Time window in seconds
        key_attr: Attribute name to use for rate limit key (e.g., 'id', 'user_id')
        key_prefix: Prefix for the rate limit key
        limiter: RateLimiter instance to use
        raise_on_exceeded: Whether to raise RateLimitExceeded or return None

    Example:
        >>> class User:
        >>>     def __init__(self, user_id: str):
        >>>         self.id = user_id
        >>>
        >>>     @rate_limit_method(rate=10, period=60, key_attr="id", key_prefix="user")
        >>>     async def make_request(self):
        >>>         return "data"
        >>>
        >>> user = User("123")
        >>> await user.make_request()  # Rate limited by user.id
    """
    _limiter = limiter or RateLimiter()

    def decorator(func: F) -> F:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("rate_limit_method decorator only supports async methods")

        @functools.wraps(func)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            # Extract key from instance attribute
            key_value = getattr(self, key_attr, None)
            if key_value is None:
                raise ValueError(f"Instance has no attribute '{key_attr}' for rate limiting")

            key = f"{key_prefix}:{key_value}" if key_prefix else str(key_value)

            # Check rate limit
            try:
                result = await _limiter.check(
                    key=key,
                    rate=rate,
                    period=period,
                    raise_on_exceeded=raise_on_exceeded,
                )

                if not result.allowed and not raise_on_exceeded:
                    return None

                # Call original method if allowed
                return await func(self, *args, **kwargs)

            except RateLimitExceeded:
                if raise_on_exceeded:
                    raise
                return None

        return cast(F, wrapper)

    return decorator
