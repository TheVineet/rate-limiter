from src.rate_limiter.redis_atomic import TokenBucket as TokenBucketAtomic
from src.rate_limiter.redis_naive import TokenBucket as TokenBucketNaive
import asyncio
import pytest


@pytest.mark.asyncio
async def test_concurrency_naive(redis_client):
    bucket = TokenBucketNaive(
        redis_client=redis_client, refill_rate=0, capacity=3, token_value=1
    )
    tasks = [bucket.consume("Client_A") for _ in range(100)]
    results = await asyncio.gather(*tasks)

    allowed = sum(results)

    assert allowed > 3


@pytest.mark.asyncio
async def test_concurrency_atomic(redis_client):
    bucket = TokenBucketAtomic(
        redis_client=redis_client, refill_rate=0, capacity=3, token_value=1
    )

    tasks = [bucket.consume("Client_A") for _ in range(100)]

    results = await asyncio.gather(*tasks)

    allowed = sum(res["allowed"] for res in results)

    assert allowed == 3
