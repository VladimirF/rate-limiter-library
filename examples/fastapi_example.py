"""
Example FastAPI application with rate limiting.

This example demonstrates multiple ways to add rate limiting to FastAPI:
1. Global middleware for all endpoints
2. Per-endpoint decorators
3. Manual rate limit checks in endpoint logic

Run with: uvicorn examples.fastapi_example:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rate_limiter import RateLimiter, RateLimitExceeded
from rate_limiter.middleware import RateLimitMiddleware
from rate_limiter.types import BackendConfig

# Initialize FastAPI app
app = FastAPI(
    title="Rate Limited API",
    description="Example API with distributed rate limiting",
    version="1.0.0",
)

# Initialize rate limiter with Redis backend
# Falls back to in-memory if Redis unavailable
limiter = RateLimiter(
    redis_config=BackendConfig(host="localhost", port=6379, db=0),
    algorithm="token_bucket",
    auto_fallback=True,
)


# Option 1: Global middleware for all endpoints
# Limits requests by IP address
app.add_middleware(
    RateLimitMiddleware,
    limiter=limiter,
    rate=100,  # 100 requests
    period=60.0,  # per 60 seconds
    key_func=lambda request: request.client.host if request.client else "unknown",
    exempt_paths=["/health", "/"],  # Exempt these paths
)


@app.on_event("startup")
async def startup():
    """Startup event handler."""
    health = await limiter.health_check()
    print("Rate Limiter Health:", health)


@app.on_event("shutdown")
async def shutdown():
    """Shutdown event handler."""
    await limiter.close()


@app.get("/")
async def root():
    """Root endpoint - exempt from rate limiting."""
    return {
        "message": "Rate Limited API",
        "endpoints": {
            "/health": "Health check (no rate limit)",
            "/api/data": "Get data (global rate limit)",
            "/api/user/{user_id}": "User endpoint (per-user rate limit)",
            "/api/expensive": "Expensive operation (strict rate limit)",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint - exempt from rate limiting."""
    health = await limiter.health_check()
    return {
        "status": "healthy",
        "rate_limiter": health,
    }


@app.get("/api/data")
async def get_data(request: Request):
    """
    Simple endpoint protected by global middleware.

    Rate limited by client IP: 100 requests per 60 seconds.
    """
    return {
        "data": "some data",
        "message": "This endpoint is protected by global rate limiting",
    }


@app.get("/api/user/{user_id}")
async def get_user_data(user_id: str, request: Request):
    """
    User-specific endpoint with per-user rate limiting.

    Rate limited per user: 10 requests per 60 seconds.
    This is in addition to the global IP-based rate limit.
    """
    # Option 2: Manual rate limit check in endpoint
    try:
        result = await limiter.check(
            key=f"user:{user_id}", rate=10, period=60.0, raise_on_exceeded=True
        )
    except RateLimitExceeded as e:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded for this user",
                "retry_after": e.retry_after,
            },
            headers={"Retry-After": str(int(e.retry_after or 0))},
        )

    return {
        "user_id": user_id,
        "data": "user specific data",
        "rate_limit": {
            "remaining": result.remaining,
            "limit": result.limit,
            "reset_at": result.reset_at,
        },
    }


@app.post("/api/expensive")
async def expensive_operation(request: Request):
    """
    Expensive operation with strict rate limiting.

    Rate limited by IP: 5 requests per minute.
    This is separate from the global rate limit.
    """
    client_ip = request.client.host if request.client else "unknown"

    # Check rate limit for expensive operations
    result = await limiter.check(
        key=f"expensive:{client_ip}", rate=5, period=60.0, raise_on_exceeded=False
    )

    if not result.allowed:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too many expensive operations",
                "retry_after": result.retry_after,
                "message": "This endpoint is rate limited to 5 requests per minute",
            },
            headers={"Retry-After": str(int(result.retry_after))},
        )

    # Simulate expensive operation
    return {
        "status": "success",
        "message": "Expensive operation completed",
        "rate_limit": {
            "remaining": result.remaining,
            "limit": result.limit,
        },
    }


@app.get("/api/stats/{key}")
async def get_rate_limit_stats(key: str):
    """
    Get rate limit statistics for a specific key.

    This endpoint helps debug and monitor rate limit usage.
    """
    usage = await limiter.get_usage(key)
    health = await limiter.health_check()

    return {
        "key": key,
        "usage": usage,
        "backend_health": health,
        "using_fallback": limiter.is_using_fallback,
    }


@app.delete("/api/reset/{key}")
async def reset_rate_limit(key: str):
    """
    Reset rate limit for a specific key.

    Useful for administrative purposes or testing.
    """
    await limiter.reset(key)

    return {
        "status": "success",
        "message": f"Rate limit reset for key: {key}",
    }


if __name__ == "__main__":
    import uvicorn

    print("Starting FastAPI application with rate limiting...")
    print("Visit http://localhost:8000/docs for interactive API documentation")
    uvicorn.run(app, host="0.0.0.0", port=8000)
