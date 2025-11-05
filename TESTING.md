# Testing Guide

This project uses industry-standard testing practices with real Redis instances for integration tests.

## Testing Approach

### 1. Unit Tests (In-Memory Backend)
- Test the token bucket algorithm implementation
- No external dependencies
- Fast execution
- 100% code coverage on core logic

### 2. Integration Tests (Redis Backend)
- Use **testcontainers-python** to spin up real Redis instances in Docker
- Tests run against actual Redis, not mocks
- Ensures Lua scripts work correctly
- Validates distributed rate limiting across multiple clients

### 3. End-to-End Tests
- Test the complete RateLimiter with graceful degradation
- Verify fallback mechanisms
- Test decorator and middleware integrations

## Running Tests Locally

### Option 1: Using Testcontainers (Recommended)

Testcontainers automatically manages Docker containers for tests:

```bash
# Install with testcontainers support
pip install -e ".[dev]"

# Run all tests (testcontainers will auto-start Redis)
pytest

# Run specific test suites
pytest tests/test_memory_backend.py      # Unit tests only
pytest tests/test_redis_backend.py       # Redis integration tests
pytest tests/test_core.py                # End-to-end tests
```

**Requirements:**
- Docker must be installed and running
- Docker daemon must be accessible (Unix socket or TCP)

### Option 2: Using docker-compose

For local development with persistent Redis:

```bash
# Start Redis
docker-compose up -d

# Run tests against local Redis
REDIS_HOST=localhost REDIS_PORT=6379 pytest

# Stop Redis
docker-compose down
```

### Option 3: Using System Redis

If you have Redis installed locally:

```bash
# Start Redis (if not running)
redis-server

# Run tests
REDIS_HOST=localhost REDIS_PORT=6379 pytest
```

## Test Coverage

```bash
# Run tests with coverage
pytest --cov=rate_limiter --cov-report=html

# View coverage report
open htmlcov/index.html
```

Current coverage:
- Memory backend: 100%
- Redis backend: 75%+ (Lua scripts tested via integration)
- Core rate limiter: 80%+

## CI/CD Testing

The project uses GitHub Actions for continuous integration:

**Workflow: `.github/workflows/test.yml`**

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - 6379:6379
```

Tests run on:
- Python 3.11 and 3.12
- Real Redis service container
- Multiple test suites in parallel

## Performance Benchmarks

Run performance benchmarks:

```bash
python benchmarks/benchmark_throughput.py
```

Expected results:
- **In-Memory Backend**: 250k+ req/s
- **Redis Backend**: 30k+ req/s (single instance)

## Writing New Tests

### Example: Testing with Redis

```python
import pytest
from rate_limiter.backends.redis import RedisBackend
from rate_limiter.types import BackendConfig, RateLimitConfig

async def test_my_feature(redis_container):
    """Test using real Redis container."""
    # redis_container fixture provides connection info
    config = BackendConfig(
        host=redis_container["host"],
        port=redis_container["port"],
        db=0,
    )

    backend = RedisBackend(config=config)

    # Your test logic here
    result = await backend.check_rate_limit(
        RateLimitConfig(rate=10, period=60, key="test_key")
    )

    assert result.allowed is True
```

### Example: Using Pre-Connected Client

```python
async def test_with_client(redis_client):
    """Test using pre-connected Redis client."""
    # redis_client fixture provides an async Redis client
    await redis_client.set("test", "value")
    value = await redis_client.get("test")
    assert value == "value"
```

## Troubleshooting

### Docker Not Available

If Docker is not available, tests will skip Redis integration tests:

```
SKIPPED [1] tests/conftest.py:41: testcontainers not available
```

**Solution**: Install Docker or set `REDIS_HOST` environment variable.

### Port Already in Use

If port 6379 is already in use:

```bash
# Kill existing Redis
docker stop $(docker ps -q --filter ancestor=redis)

# Or use custom port
REDIS_PORT=6380 pytest
```

### Testcontainers Permission Issues

On Linux, ensure your user is in the `docker` group:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

## Best Practices

1. **Always test against real Redis** for integration tests
2. **Use testcontainers** for isolated, reproducible tests
3. **Clean up resources** - fixtures handle this automatically
4. **Test concurrency** - verify thread-safety with concurrent requests
5. **Test failures** - ensure graceful degradation works

## Continuous Integration

The CI pipeline runs:

1. **Linting**: Black, Ruff, MyPy
2. **Unit Tests**: Fast tests with in-memory backend
3. **Integration Tests**: Real Redis via service containers
4. **Benchmarks**: Performance validation
5. **Coverage Report**: Uploaded to Codecov

All tests must pass before merging pull requests.

## Industry Standards

This testing approach follows industry best practices:

- ✅ **Real dependencies**: No mocking Redis, test against the real thing
- ✅ **Containerization**: Reproducible test environments
- ✅ **CI/CD integration**: Automated testing on every commit
- ✅ **Multiple Python versions**: Ensure compatibility
- ✅ **Performance testing**: Continuous benchmark monitoring
- ✅ **Code coverage**: Track test completeness

This is how production systems at Google, Netflix, and Stripe test their distributed systems.
