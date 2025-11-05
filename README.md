# Distributed Rate Limiter

A high-performance, production-ready distributed rate limiting library for Python with Redis backend and automatic fallback to in-memory storage.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **🚀 High Performance**: Capable of handling 100k+ requests/second
- **🔄 Distributed**: Redis-backed for true distributed rate limiting across multiple servers
- **🛡️ Graceful Degradation**: Automatically falls back to in-memory backend if Redis fails
- **⚡ Multiple Algorithms**: Token bucket and sliding window algorithms
- **🎯 Multiple Interfaces**: Use as decorator, middleware, or direct API
- **🔒 Thread-Safe**: Safe for concurrent use
- **📊 Production Ready**: Comprehensive error handling, logging, and monitoring
- **🎨 Pythonic API**: Clean, intuitive interface following Python best practices

## Installation

```bash
# Basic installation
pip install distributed-rate-limiter

# With web framework support (FastAPI, Starlette)
pip install distributed-rate-limiter[web]

# Development installation with all dependencies
pip install distributed-rate-limiter[dev]
```

## Quick Start

### Basic Usage

```python
import asyncio
from rate_limiter import RateLimiter

async def main():
    async with RateLimiter() as limiter:
        # Check if request is allowed
        result = await limiter.check(
            key="user:123",
            rate=100,    # 100 requests
            period=60.0  # per 60 seconds
        )

        if result.allowed:
            print(f"Request allowed. Remaining: {result.remaining}")
        else:
            print(f"Rate limited. Retry after: {result.retry_after}s")

asyncio.run(main())
```

### Using Decorators

```python
from rate_limiter.decorators import rate_limit

@rate_limit(
    rate=10,
    period=60.0,
    key_func=lambda user_id: f"user:{user_id}"
)
async def api_call(user_id: str):
    return f"Data for {user_id}"

# Automatically rate limited per user
await api_call("user123")
```

### FastAPI Integration

```python
from fastapi import FastAPI
from rate_limiter.middleware import RateLimitMiddleware

app = FastAPI()

# Add global rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    rate=100,
    period=60.0,
    key_func=lambda request: request.client.host
)

@app.get("/api/data")
async def get_data():
    return {"data": "value"}
```

## Detailed Examples

### 1. Token Bucket Algorithm (Default)

The token bucket algorithm provides smooth rate limiting with gradual token refill.

```python
from rate_limiter import RateLimiter
from rate_limiter.types import BackendConfig

limiter = RateLimiter(
    redis_config=BackendConfig(
        host="localhost",
        port=6379,
        db=0
    ),
    algorithm="token_bucket",
    auto_fallback=True  # Fallback to memory if Redis fails
)

# Check rate limit
result = await limiter.check("user:123", rate=100, period=60)

print(f"Allowed: {result.allowed}")
print(f"Remaining: {result.remaining}")
print(f"Reset at: {result.reset_at}")
print(f"Retry after: {result.retry_after}s")
```

### 2. Sliding Window Algorithm

The sliding window algorithm provides stricter rate limiting guarantees.

```python
from rate_limiter import RateLimiter

limiter = RateLimiter(algorithm="sliding_window")

# More strict enforcement of rate limits
result = await limiter.check("api:endpoint", rate=1000, period=60)
```

### 3. Graceful Degradation

The library automatically falls back to in-memory storage if Redis becomes unavailable.

```python
from rate_limiter import RateLimiter
from rate_limiter.types import BackendConfig

limiter = RateLimiter(
    redis_config=BackendConfig(host="redis-host", port=6379),
    auto_fallback=True  # Enable automatic fallback
)

# Even if Redis fails, requests will be rate limited using in-memory backend
result = await limiter.check("user:123", rate=100, period=60)

# Check which backend is being used
if limiter.is_using_fallback:
    print("Using fallback backend (in-memory)")
else:
    print("Using primary backend (Redis)")

# Monitor backend health
health = await limiter.health_check()
print(health)  # {'primary': True, 'fallback': True, 'using_fallback': False}
```

### 4. Advanced FastAPI Example

```python
from fastapi import FastAPI, Request, HTTPException
from rate_limiter import RateLimiter, RateLimitExceeded
from rate_limiter.middleware import RateLimitMiddleware

app = FastAPI()
limiter = RateLimiter()

# Global rate limit: 1000 requests per minute per IP
app.add_middleware(
    RateLimitMiddleware,
    limiter=limiter,
    rate=1000,
    period=60.0,
    key_func=lambda request: request.client.host,
    exempt_paths=["/health"]
)

# Per-user endpoint with custom rate limit
@app.get("/api/user/{user_id}")
async def get_user(user_id: str):
    # Additional per-user rate limit: 10 requests per minute
    result = await limiter.check(
        key=f"user:{user_id}",
        rate=10,
        period=60.0,
        raise_on_exceeded=True  # Raise exception if exceeded
    )

    return {"user_id": user_id, "rate_limit": result}

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": str(exc), "retry_after": exc.retry_after},
        headers={"Retry-After": str(int(exc.retry_after or 0))}
    )
```

### 5. Class Method Rate Limiting

```python
from rate_limiter.decorators import rate_limit_method

class APIClient:
    def __init__(self, user_id: str):
        self.id = user_id

    @rate_limit_method(
        rate=100,
        period=60.0,
        key_attr="id",
        key_prefix="api_client"
    )
    async def fetch_data(self):
        # Rate limited per instance (by id attribute)
        return "data"

client = APIClient("user123")
await client.fetch_data()
```

### 6. Manual Backend Configuration

```python
from rate_limiter import RateLimiter
from rate_limiter.backends import RedisBackend, InMemoryBackend
from rate_limiter.types import BackendConfig

# Custom Redis configuration
redis_config = BackendConfig(
    host="redis.example.com",
    port=6379,
    db=0,
    password="secret",
    socket_timeout=2.0,
    max_connections=100
)

redis_backend = RedisBackend(config=redis_config, algorithm="token_bucket")
memory_backend = InMemoryBackend()

limiter = RateLimiter(
    backend=redis_backend,
    fallback_backend=memory_backend,
    auto_fallback=True
)
```

## Configuration Options

### RateLimiter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backend` | Backend | RedisBackend | Primary storage backend |
| `fallback_backend` | Backend | InMemoryBackend | Fallback storage backend |
| `redis_config` | BackendConfig | None | Redis configuration |
| `algorithm` | str | "token_bucket" | Algorithm: "token_bucket" or "sliding_window" |
| `auto_fallback` | bool | True | Enable automatic fallback |
| `raise_on_exceeded` | bool | False | Raise exception when rate limited |

### BackendConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | str | "localhost" | Redis host |
| `port` | int | 6379 | Redis port |
| `db` | int | 0 | Redis database number |
| `password` | str | None | Redis password |
| `socket_timeout` | float | 1.0 | Socket timeout in seconds |
| `max_connections` | int | 50 | Maximum connection pool size |

## Algorithms

### Token Bucket

- Tokens are added to a bucket at a constant rate
- Each request consumes one token
- Smooth rate limiting with gradual refill
- Better for handling bursts
- Lower memory usage

### Sliding Window

- Tracks timestamps of all requests in a time window
- Removes old requests outside the window
- Stricter rate limit enforcement
- More accurate but higher memory usage
- Better for preventing request bursts

## Performance

The library is designed for high performance:

- **100k+ req/s** with in-memory backend
- **30k+ req/s** with Redis backend (single instance)
- Atomic operations using Lua scripts (no race conditions)
- Connection pooling and pipelining
- Minimal latency overhead (~0.01ms for memory, ~1-2ms for Redis)

Run benchmarks:

```bash
python benchmarks/benchmark_throughput.py
```

## Testing

The library uses **industry-standard integration testing** with real Redis instances:

### Automated Testing with Testcontainers

The test suite uses [testcontainers-python](https://testcontainers-python.readthedocs.io/) to automatically spin up Redis Docker containers:

```bash
# Install test dependencies (includes testcontainers)
pip install -e ".[dev]"

# Run all tests (testcontainers auto-starts Redis in Docker)
pytest

# Run with coverage
pytest --cov=rate_limiter --cov-report=html

# Run specific test suites
pytest tests/test_memory_backend.py     # Unit tests (no Redis needed)
pytest tests/test_redis_backend.py      # Integration tests (uses Docker)
pytest tests/test_core.py               # End-to-end tests
```

**Requirements**: Docker must be installed and running

### Alternative: Use Existing Redis

If you have Redis running locally or in CI:

```bash
# Start Redis (local or docker-compose)
docker-compose up -d redis

# Run tests with existing Redis
REDIS_HOST=localhost REDIS_PORT=6379 pytest
```

### Why Real Redis?

- ✅ **No Mocks**: Tests run against actual Redis, catching real-world issues
- ✅ **Lua Script Validation**: Ensures atomic operations work correctly
- ✅ **Distributed Testing**: Verifies rate limit sharing across instances
- ✅ **Production Parity**: Same environment as production

See [TESTING.md](TESTING.md) for detailed testing documentation.

## Development

### Project Structure

```
rate-limiter-library/
├── rate_limiter/
│   ├── __init__.py           # Main exports
│   ├── core.py               # RateLimiter class
│   ├── decorators.py         # Decorator implementations
│   ├── middleware.py         # ASGI middleware
│   ├── exceptions.py         # Custom exceptions
│   ├── types.py              # Type definitions
│   └── backends/
│       ├── base.py           # Backend protocol
│       ├── memory.py         # In-memory backend
│       └── redis.py          # Redis backend with Lua scripts
├── tests/
│   ├── test_core.py
│   ├── test_memory_backend.py
│   └── test_redis_backend.py
├── benchmarks/
│   └── benchmark_throughput.py
├── examples/
│   ├── fastapi_example.py
│   └── decorator_example.py
└── pyproject.toml
```

### Code Style

The project follows Python best practices:

- **Type hints**: Full type annotations for better IDE support
- **Async/await**: Modern async Python patterns
- **Protocols**: Clean abstractions using Protocol classes
- **Context managers**: Proper resource management
- **Error handling**: Comprehensive exception handling
- **Documentation**: Extensive docstrings and comments

### Design Patterns

- **Strategy Pattern**: Pluggable backends
- **Decorator Pattern**: Function/method rate limiting
- **Circuit Breaker**: Graceful degradation
- **Factory Pattern**: Backend creation

## Production Deployment

### Recommended Configuration

```python
from rate_limiter import RateLimiter
from rate_limiter.types import BackendConfig

# Production configuration
limiter = RateLimiter(
    redis_config=BackendConfig(
        host="redis.prod.example.com",
        port=6379,
        db=0,
        password="strong_password",
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
        max_connections=200  # Adjust based on traffic
    ),
    algorithm="token_bucket",
    auto_fallback=True,  # Always enable for production
    raise_on_exceeded=False  # Return result instead of raising
)
```

### Monitoring

```python
# Regular health checks
async def monitor_rate_limiter():
    health = await limiter.health_check()

    if not health['primary']:
        # Alert: Primary backend down
        logger.error("Redis backend unhealthy")

    if health['using_fallback']:
        # Alert: Using fallback
        logger.warning("Rate limiter using fallback backend")
```

### Redis Setup

For high availability in production:

1. **Redis Sentinel** for automatic failover
2. **Redis Cluster** for horizontal scaling
3. **Persistence**: Enable AOF for data durability
4. **Memory management**: Set maxmemory and eviction policy

```redis
# redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
appendonly yes
```

## API Reference

### RateLimiter

#### `async check(key, rate, period, raise_on_exceeded=None) -> RateLimitResult`

Check if request is allowed.

#### `async allow(key, rate, period) -> bool`

Simple boolean check.

#### `async reset(key) -> None`

Reset rate limit for a key.

#### `async get_usage(key) -> int`

Get current usage count.

#### `async health_check() -> dict`

Check backend health.

### RateLimitResult

```python
@dataclass
class RateLimitResult:
    allowed: bool          # Whether request is allowed
    remaining: int         # Remaining requests
    limit: int            # Total limit
    retry_after: float    # Seconds to wait if denied
    reset_at: float       # Unix timestamp of reset
```

## Troubleshooting

### Redis Connection Issues

```python
# Increase timeouts for slow networks
config = BackendConfig(
    socket_timeout=5.0,
    socket_connect_timeout=5.0
)
```

### High Latency

```python
# Increase connection pool size
config = BackendConfig(max_connections=200)

# Or use in-memory backend for single-instance deployments
limiter = RateLimiter(backend=InMemoryBackend())
```

### Memory Usage

```python
# Use token bucket (lower memory) instead of sliding window
limiter = RateLimiter(algorithm="token_bucket")
```

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- Inspired by production rate limiters at GitHub, Stripe, and Kong
- Redis Lua scripting for atomic operations
- Python async/await for high performance