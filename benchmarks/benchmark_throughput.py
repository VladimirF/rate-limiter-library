"""Throughput benchmarks for rate limiter.

This benchmark aims to demonstrate 100k+ requests/second throughput.
"""

import asyncio
import time
from statistics import mean, median, stdev

from rate_limiter.backends.memory import InMemoryBackend
from rate_limiter.backends.redis import RedisBackend
from rate_limiter.core import RateLimiter
from rate_limiter.types import BackendConfig, RateLimitConfig


class BenchmarkRunner:
    """Runner for performance benchmarks."""

    def __init__(self, name: str):
        self.name = name
        self.results: list[float] = []

    async def run_benchmark(
        self, backend, num_requests: int, concurrent_tasks: int, key_pool_size: int = 100
    ) -> dict:
        """Run benchmark with specified parameters.

        Args:
            backend: Backend to benchmark
            num_requests: Total number of requests to make
            concurrent_tasks: Number of concurrent tasks
            key_pool_size: Number of unique keys to use

        Returns:
            Dictionary with benchmark results
        """
        # Use high rate limit for benchmarking throughput
        rate = 1000000
        period = 60.0

        # Generate pool of keys for more realistic testing
        keys = [f"bench_user_{i}" for i in range(key_pool_size)]

        async def worker(task_id: int, requests_per_task: int):
            """Worker coroutine that makes rate limit checks."""
            for i in range(requests_per_task):
                key_idx = (task_id * requests_per_task + i) % key_pool_size
                config = RateLimitConfig(
                    rate=rate,
                    period=period,
                    key=keys[key_idx],
                )
                await backend.check_rate_limit(config)

        requests_per_task = num_requests // concurrent_tasks

        # Warm up
        warmup_config = RateLimitConfig(rate=1000000, period=60.0, key="warmup")
        for _ in range(100):
            await backend.check_rate_limit(warmup_config)

        # Run benchmark
        start_time = time.perf_counter()

        tasks = [worker(i, requests_per_task) for i in range(concurrent_tasks)]
        await asyncio.gather(*tasks)

        end_time = time.perf_counter()

        elapsed = end_time - start_time
        total_requests = requests_per_task * concurrent_tasks
        throughput = total_requests / elapsed

        return {
            "name": self.name,
            "total_requests": total_requests,
            "elapsed_seconds": elapsed,
            "throughput_rps": throughput,
            "concurrent_tasks": concurrent_tasks,
            "key_pool_size": key_pool_size,
            "avg_latency_ms": (elapsed / total_requests) * 1000,
        }


async def benchmark_memory_backend():
    """Benchmark in-memory backend."""
    print("\n" + "=" * 80)
    print("BENCHMARK: In-Memory Backend")
    print("=" * 80)

    backend = InMemoryBackend()
    runner = BenchmarkRunner("InMemoryBackend")

    try:
        # Test with increasing concurrency
        test_configs = [
            (100000, 100, 100),  # 100k requests, 100 concurrent, 100 keys
            (500000, 500, 100),  # 500k requests, 500 concurrent, 100 keys
            (1000000, 1000, 1000),  # 1M requests, 1000 concurrent, 1000 keys
        ]

        results = []
        for num_requests, concurrent_tasks, key_pool_size in test_configs:
            print(
                f"\nRunning: {num_requests:,} requests, "
                f"{concurrent_tasks} concurrent tasks, "
                f"{key_pool_size} unique keys"
            )

            result = await runner.run_benchmark(
                backend, num_requests, concurrent_tasks, key_pool_size
            )
            results.append(result)

            print(f"  Throughput: {result['throughput_rps']:,.0f} req/s")
            print(f"  Elapsed: {result['elapsed_seconds']:.2f}s")
            print(f"  Avg Latency: {result['avg_latency_ms']:.4f}ms")

        print("\n" + "-" * 80)
        print("Summary:")
        throughputs = [r["throughput_rps"] for r in results]
        print(f"  Max Throughput: {max(throughputs):,.0f} req/s")
        print(f"  Avg Throughput: {mean(throughputs):,.0f} req/s")

        return results

    finally:
        await backend.close()


async def benchmark_redis_backend():
    """Benchmark Redis backend."""
    print("\n" + "=" * 80)
    print("BENCHMARK: Redis Backend (Token Bucket)")
    print("=" * 80)

    config = BackendConfig(
        host="localhost",
        port=6379,
        db=14,
        max_connections=200,  # Increased for high concurrency
    )

    backend = RedisBackend(config=config, algorithm="token_bucket")

    # Check Redis availability
    try:
        if not await backend.health_check():
            print("Redis not available, skipping Redis benchmarks")
            await backend.close()
            return []
    except Exception as e:
        print(f"Redis not available: {e}, skipping Redis benchmarks")
        await backend.close()
        return []

    runner = BenchmarkRunner("RedisBackend-TokenBucket")

    try:
        test_configs = [
            (10000, 50, 100),  # 10k requests, 50 concurrent, 100 keys
            (50000, 100, 100),  # 50k requests, 100 concurrent, 100 keys
            (100000, 200, 500),  # 100k requests, 200 concurrent, 500 keys
        ]

        results = []
        for num_requests, concurrent_tasks, key_pool_size in test_configs:
            print(
                f"\nRunning: {num_requests:,} requests, "
                f"{concurrent_tasks} concurrent tasks, "
                f"{key_pool_size} unique keys"
            )

            result = await runner.run_benchmark(
                backend, num_requests, concurrent_tasks, key_pool_size
            )
            results.append(result)

            print(f"  Throughput: {result['throughput_rps']:,.0f} req/s")
            print(f"  Elapsed: {result['elapsed_seconds']:.2f}s")
            print(f"  Avg Latency: {result['avg_latency_ms']:.4f}ms")

        print("\n" + "-" * 80)
        print("Summary:")
        throughputs = [r["throughput_rps"] for r in results]
        print(f"  Max Throughput: {max(throughputs):,.0f} req/s")
        print(f"  Avg Throughput: {mean(throughputs):,.0f} req/s")

        return results

    finally:
        await backend.close()


async def benchmark_sliding_window():
    """Benchmark sliding window algorithm."""
    print("\n" + "=" * 80)
    print("BENCHMARK: Redis Backend (Sliding Window)")
    print("=" * 80)

    config = BackendConfig(host="localhost", port=6379, db=14, max_connections=200)

    backend = RedisBackend(config=config, algorithm="sliding_window")

    try:
        if not await backend.health_check():
            print("Redis not available, skipping sliding window benchmarks")
            await backend.close()
            return []
    except Exception:
        print("Redis not available, skipping sliding window benchmarks")
        await backend.close()
        return []

    runner = BenchmarkRunner("RedisBackend-SlidingWindow")

    try:
        test_configs = [
            (10000, 50, 100),
            (50000, 100, 100),
        ]

        results = []
        for num_requests, concurrent_tasks, key_pool_size in test_configs:
            print(
                f"\nRunning: {num_requests:,} requests, "
                f"{concurrent_tasks} concurrent tasks, "
                f"{key_pool_size} unique keys"
            )

            result = await runner.run_benchmark(
                backend, num_requests, concurrent_tasks, key_pool_size
            )
            results.append(result)

            print(f"  Throughput: {result['throughput_rps']:,.0f} req/s")
            print(f"  Elapsed: {result['elapsed_seconds']:.2f}s")
            print(f"  Avg Latency: {result['avg_latency_ms']:.4f}ms")

        print("\n" + "-" * 80)
        print("Summary:")
        throughputs = [r["throughput_rps"] for r in results]
        print(f"  Max Throughput: {max(throughputs):,.0f} req/s")
        print(f"  Avg Throughput: {mean(throughputs):,.0f} req/s")

        return results

    finally:
        await backend.close()


async def main():
    """Run all benchmarks."""
    print("\n")
    print("=" * 80)
    print(" DISTRIBUTED RATE LIMITER - PERFORMANCE BENCHMARKS")
    print("=" * 80)
    print("\nObjective: Demonstrate 100k+ requests/second throughput")
    print()

    all_results = []

    # Run memory backend benchmark
    memory_results = await benchmark_memory_backend()
    all_results.extend(memory_results)

    # Run Redis benchmarks
    redis_results = await benchmark_redis_backend()
    all_results.extend(redis_results)

    # Run sliding window benchmark
    sliding_results = await benchmark_sliding_window()
    all_results.extend(sliding_results)

    # Overall summary
    print("\n" + "=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)

    for result in all_results:
        print(f"\n{result['name']}:")
        print(f"  Max Throughput: {result['throughput_rps']:,.0f} req/s")
        print(f"  Requests: {result['total_requests']:,}")
        print(f"  Concurrency: {result['concurrent_tasks']}")

    # Check if we met the 100k req/s target
    max_throughput = max((r["throughput_rps"] for r in all_results), default=0)

    print("\n" + "=" * 80)
    if max_throughput >= 100000:
        print(f"✓ SUCCESS: Achieved {max_throughput:,.0f} req/s (target: 100k+ req/s)")
    else:
        print(f"○ Result: {max_throughput:,.0f} req/s (target: 100k+ req/s)")
    print("=" * 80)
    print()


if __name__ == "__main__":
    asyncio.run(main())
