"""ASGI middleware for rate limiting web applications."""

import logging
from typing import Awaitable, Callable

from rate_limiter.core import RateLimiter
from rate_limiter.exceptions import RateLimitExceeded

logger = logging.getLogger(__name__)

try:
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.types import ASGIApp

    STARLETTE_AVAILABLE = True
except ImportError:
    STARLETTE_AVAILABLE = False
    Request = None  # type: ignore
    Response = None  # type: ignore
    ASGIApp = None  # type: ignore
    JSONResponse = None  # type: ignore


class RateLimitMiddleware:
    """ASGI middleware for rate limiting HTTP requests.

    Compatible with FastAPI, Starlette, and other ASGI frameworks.

    Example with FastAPI:
        >>> from fastapi import FastAPI
        >>> from rate_limiter.middleware import RateLimitMiddleware
        >>>
        >>> app = FastAPI()
        >>> app.add_middleware(
        >>>     RateLimitMiddleware,
        >>>     rate=100,
        >>>     period=60,
        >>>     key_func=lambda request: request.client.host
        >>> )
    """

    def __init__(
        self,
        app: "ASGIApp",
        limiter: RateLimiter | None = None,
        rate: int = 100,
        period: float = 60.0,
        key_func: Callable[["Request"], str] | None = None,
        exempt_paths: list[str] | None = None,
        on_rate_limited: Callable[["Request", float], "Response"] | None = None,
    ) -> None:
        """Initialize rate limit middleware.

        Args:
            app: ASGI application
            limiter: RateLimiter instance (creates default if None)
            rate: Maximum requests allowed
            period: Time window in seconds
            key_func: Function to extract rate limit key from request
                     (defaults to client IP)
            exempt_paths: List of paths to exempt from rate limiting
            on_rate_limited: Custom handler for rate limited responses
        """
        if not STARLETTE_AVAILABLE:
            raise ImportError(
                "Starlette is required for middleware. Install with: "
                "pip install 'distributed-rate-limiter[web]'"
            )

        self.app = app
        self.limiter = limiter or RateLimiter()
        self.rate = rate
        self.period = period
        self.key_func = key_func or self._default_key_func
        self.exempt_paths = set(exempt_paths or [])
        self.on_rate_limited = on_rate_limited or self._default_rate_limited_response

    @staticmethod
    def _default_key_func(request: "Request") -> str:
        """Default key function using client IP address."""
        # Try to get real IP from common proxy headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    @staticmethod
    def _default_rate_limited_response(request: "Request", retry_after: float) -> "Response":
        """Default response for rate limited requests."""
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too Many Requests",
                "message": "Rate limit exceeded. Please try again later.",
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(int(retry_after))},
        )

    async def __call__(
        self,
        scope: dict,  # type: ignore
        receive: Callable,  # type: ignore
        send: Callable,  # type: ignore
    ) -> None:
        """ASGI application callable."""
        if scope["type"] != "http":
            # Pass through non-HTTP requests (e.g., WebSocket)
            await self.app(scope, receive, send)
            return

        # Create request object
        request = Request(scope, receive)

        # Check if path is exempt
        if request.url.path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        # Extract rate limit key
        try:
            key = self.key_func(request)
        except Exception as e:
            logger.warning(f"Failed to extract rate limit key: {e}")
            key = "unknown"

        # Check rate limit
        try:
            result = await self.limiter.check(
                key=key, rate=self.rate, period=self.period, raise_on_exceeded=False
            )

            # Add rate limit headers to response
            async def send_with_headers(message: dict) -> None:  # type: ignore
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.extend(
                        [
                            (b"X-RateLimit-Limit", str(result.limit).encode()),
                            (b"X-RateLimit-Remaining", str(result.remaining).encode()),
                            (b"X-RateLimit-Reset", str(int(result.reset_at)).encode()),
                        ]
                    )
                    message["headers"] = headers
                await send(message)

            if result.allowed:
                # Request allowed, pass through with rate limit headers
                await self.app(scope, receive, send_with_headers)
            else:
                # Request denied, send rate limited response
                response = self.on_rate_limited(request, result.retry_after)
                await response(scope, receive, send)

        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # On error, allow request to proceed (fail open)
            await self.app(scope, receive, send)


class RateLimitDecorator:
    """Decorator for rate limiting individual endpoints.

    Example with FastAPI:
        >>> from fastapi import FastAPI, Request
        >>> from rate_limiter.middleware import RateLimitDecorator
        >>>
        >>> app = FastAPI()
        >>> rate_limiter = RateLimitDecorator(rate=10, period=60)
        >>>
        >>> @app.get("/api/data")
        >>> @rate_limiter
        >>> async def get_data(request: Request):
        >>>     return {"data": "value"}
    """

    def __init__(
        self,
        limiter: RateLimiter | None = None,
        rate: int = 100,
        period: float = 60.0,
        key_func: Callable[["Request"], str] | None = None,
    ) -> None:
        """Initialize rate limit decorator.

        Args:
            limiter: RateLimiter instance
            rate: Maximum requests allowed
            period: Time window in seconds
            key_func: Function to extract rate limit key from request
        """
        if not STARLETTE_AVAILABLE:
            raise ImportError(
                "Starlette is required for decorators. Install with: "
                "pip install 'distributed-rate-limiter[web]'"
            )

        self.limiter = limiter or RateLimiter()
        self.rate = rate
        self.period = period
        self.key_func = key_func or RateLimitMiddleware._default_key_func

    def __call__(
        self, func: Callable[..., Awaitable[Response]]
    ) -> Callable[..., Awaitable[Response]]:
        """Decorate endpoint function."""

        async def wrapper(*args, **kwargs) -> Response:  # type: ignore
            # Extract request object from args/kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if request is None and "request" in kwargs:
                request = kwargs["request"]

            if request is None:
                raise ValueError(
                    "Rate limit decorator requires Request object in function signature"
                )

            # Extract rate limit key
            key = self.key_func(request)

            # Check rate limit
            try:
                await self.limiter.check(
                    key=key, rate=self.rate, period=self.period, raise_on_exceeded=True
                )
            except RateLimitExceeded as e:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too Many Requests",
                        "message": str(e),
                        "retry_after": e.retry_after,
                    },
                    headers={"Retry-After": str(int(e.retry_after or 0))},
                )

            # Call original function
            return await func(*args, **kwargs)

        return wrapper
