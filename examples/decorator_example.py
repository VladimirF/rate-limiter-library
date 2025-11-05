"""
Example demonstrating decorator-based rate limiting.

Shows how to use @rate_limit decorator for easy function protection.
"""

import asyncio

from rate_limiter import RateLimiter
from rate_limiter.decorators import rate_limit, rate_limit_method
from rate_limiter.exceptions import RateLimitExceeded


# Create a shared rate limiter instance
limiter = RateLimiter()


# Example 1: Simple function rate limiting
@rate_limit(rate=5, period=10.0, limiter=limiter)
async def send_email(to: str, subject: str):
    """Send email - limited to 5 calls per 10 seconds globally."""
    print(f"Sending email to {to}: {subject}")
    await asyncio.sleep(0.1)  # Simulate sending
    return "Email sent"


# Example 2: Per-user rate limiting with key function
@rate_limit(
    rate=10,
    period=60.0,
    key_func=lambda user_id, **kwargs: f"api:user:{user_id}",
    limiter=limiter,
)
async def make_api_call(user_id: str, endpoint: str):
    """Make API call - limited per user (10 per minute)."""
    print(f"User {user_id} calling {endpoint}")
    return {"status": "success", "endpoint": endpoint}


# Example 3: Rate limited class methods
class UserService:
    """Service with rate limited methods."""

    def __init__(self, user_id: str):
        self.id = user_id
        self.name = f"User_{user_id}"

    @rate_limit_method(rate=5, period=60.0, key_attr="id", key_prefix="user_service", limiter=limiter)
    async def fetch_data(self):
        """Fetch user data - rate limited per user instance."""
        print(f"Fetching data for {self.name}")
        await asyncio.sleep(0.05)
        return {"user": self.name, "data": "some data"}

    @rate_limit_method(rate=2, period=60.0, key_attr="id", key_prefix="user_update", limiter=limiter)
    async def update_profile(self, new_name: str):
        """Update user profile - strictly limited (2 per minute)."""
        print(f"Updating profile for {self.name} to {new_name}")
        self.name = new_name
        return {"success": True}


# Example 4: Handling rate limit exceptions
@rate_limit(rate=3, period=5.0, limiter=limiter, raise_on_exceeded=True)
async def critical_operation():
    """Critical operation that raises exception when rate limited."""
    print("Executing critical operation")
    return "completed"


async def demo_simple_function():
    """Demo simple function rate limiting."""
    print("\n" + "=" * 60)
    print("Demo 1: Simple Function Rate Limiting")
    print("=" * 60)
    print("Limit: 5 calls per 10 seconds\n")

    # Make 5 successful calls
    for i in range(5):
        result = await send_email(f"user{i}@example.com", f"Test {i}")
        print(f"  ✓ Call {i+1}: {result}")

    # 6th call will be rate limited
    print("\n  Attempting 6th call (should be rate limited)...")
    try:
        await send_email("user6@example.com", "Test 6")
    except RateLimitExceeded as e:
        print(f"  ✗ Rate limited! Retry after: {e.retry_after:.2f}s")


async def demo_per_user_limiting():
    """Demo per-user rate limiting."""
    print("\n" + "=" * 60)
    print("Demo 2: Per-User Rate Limiting")
    print("=" * 60)
    print("Limit: 10 calls per 60 seconds per user\n")

    # User 1 makes calls
    print("User 'alice' making calls:")
    for i in range(3):
        result = await make_api_call("alice", f"/api/endpoint{i}")
        print(f"  ✓ Call {i+1}: {result['status']}")

    # User 2 makes calls (independent limit)
    print("\nUser 'bob' making calls:")
    for i in range(3):
        result = await make_api_call("bob", f"/api/endpoint{i}")
        print(f"  ✓ Call {i+1}: {result['status']}")

    print("\n  → Each user has independent rate limits")


async def demo_class_methods():
    """Demo rate limited class methods."""
    print("\n" + "=" * 60)
    print("Demo 3: Rate Limited Class Methods")
    print("=" * 60)

    user1 = UserService("user_123")
    user2 = UserService("user_456")

    print(f"\n{user1.name} fetching data (limit: 5/min):")
    for i in range(3):
        result = await user1.fetch_data()
        print(f"  ✓ Fetch {i+1}: {result}")

    print(f"\n{user2.name} fetching data (independent limit):")
    result = await user2.fetch_data()
    print(f"  ✓ Fetch 1: {result}")

    print(f"\n{user1.name} updating profile (limit: 2/min):")
    result = await user1.update_profile("Alice")
    print(f"  ✓ Update 1: {result}")

    result = await user1.update_profile("Alice Smith")
    print(f"  ✓ Update 2: {result}")

    print(f"\n  Attempting 3rd update (should be rate limited)...")
    try:
        await user1.update_profile("Alice J. Smith")
    except RateLimitExceeded as e:
        print(f"  ✗ Rate limited! Retry after: {e.retry_after:.2f}s")


async def demo_exception_handling():
    """Demo exception handling for rate limits."""
    print("\n" + "=" * 60)
    print("Demo 4: Exception Handling")
    print("=" * 60)
    print("Limit: 3 calls per 5 seconds\n")

    # Make 3 successful calls
    for i in range(3):
        result = await critical_operation()
        print(f"  ✓ Operation {i+1}: {result}")

    # 4th call raises exception
    print("\n  Attempting 4th call...")
    try:
        await critical_operation()
    except RateLimitExceeded as e:
        print(f"  ✗ RateLimitExceeded raised!")
        print(f"     Message: {e}")
        print(f"     Retry after: {e.retry_after:.2f}s")


async def demo_rate_limiter_methods():
    """Demo direct RateLimiter methods."""
    print("\n" + "=" * 60)
    print("Demo 5: Direct RateLimiter Usage")
    print("=" * 60)

    # Check health
    health = await limiter.health_check()
    print(f"\nHealth check: {health}")
    print(f"Using fallback: {limiter.is_using_fallback}")

    # Manual rate limit check
    print("\n  Manual rate limit checks:")
    for i in range(3):
        result = await limiter.check("demo_key", rate=5, period=60)
        print(f"    Call {i+1}: allowed={result.allowed}, remaining={result.remaining}")

    # Get usage
    usage = await limiter.get_usage("demo_key")
    print(f"\n  Current usage: {usage}")

    # Reset
    await limiter.reset("demo_key")
    print(f"  Reset complete")

    # Check again
    result = await limiter.check("demo_key", rate=5, period=60)
    print(f"    After reset: allowed={result.allowed}, remaining={result.remaining}")


async def main():
    """Run all demos."""
    print("\n")
    print("=" * 60)
    print("  RATE LIMITER DECORATOR EXAMPLES")
    print("=" * 60)

    try:
        await demo_simple_function()
        await demo_per_user_limiting()
        await demo_class_methods()
        await demo_exception_handling()
        await demo_rate_limiter_methods()

        print("\n" + "=" * 60)
        print("  All demos completed!")
        print("=" * 60)
        print()

    finally:
        await limiter.close()


if __name__ == "__main__":
    asyncio.run(main())
