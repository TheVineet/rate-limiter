from src.rate_limiter.redis_atomic import TokenBucket
from unittest.mock import patch
import pytest


@pytest.mark.asyncio
async def test_rejects_when_bucket_is_empty(redis_client):
    bucket = TokenBucket(refill_rate=0, capacity=3, redis_client=redis_client)
    res1 = await bucket.consume("Client_A")
    assert res1.get("allowed") is 1

    res2 = await bucket.consume("Client_A")
    assert res2.get("allowed") is 1

    res3 = await bucket.consume("Client_A")
    assert res3.get("allowed") is 1

    res4 = await bucket.consume("Client_A")
    assert res4.get("allowed") is 0


@pytest.mark.asyncio
async def test_refill_all_after_empty(redis_client):
    mock_time = 100.0

    with patch("time.monotonic", side_effect=lambda: mock_time):
        bucket = TokenBucket(refill_rate=1, capacity=3, redis_client=redis_client)
        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 1

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 1

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 1

        res = await bucket.consume("Client_A")  # Bucket is now empty
        assert res.get("allowed") is 0

        mock_time += 1  # Fast forward by 1 second

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 1  # 1 Token refilled

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 0  # Bucket is empty again


@pytest.mark.asyncio
async def test_never_exceed_capacity(redis_client):
    mock_time = 100.0
    with patch("time.monotonic", side_effect=lambda: mock_time):
        bucket = TokenBucket(refill_rate=100, capacity=3, redis_client=redis_client)
        mock_time += 100  # Fast forward 100 seconds

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 1

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 1

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 1

        res = await bucket.consume("Client_A")
        assert res.get("allowed") is 0  # Bucket is now empty


@pytest.mark.asyncio
async def test_client_isolation(redis_client):
    bucket = TokenBucket(refill_rate=0, capacity=3, redis_client=redis_client)
    res = await bucket.consume("Client_A")
    assert res.get("allowed") is 1

    res = await bucket.consume("Client_A")
    assert res.get("allowed") is 1

    res = await bucket.consume("Client_A")
    assert res.get("allowed") is 1

    res = await bucket.consume("Client_A")
    assert res.get("allowed") is 0

    res = await bucket.consume("Client_B")
    assert res.get("allowed") is 1

    res = await bucket.consume("Client_B")
    assert res.get("allowed") is 1

    res = await bucket.consume("Client_B")
    assert res.get("allowed") is 1

    res = await bucket.consume("Client_B")
    assert res.get("allowed") is 0


@pytest.mark.asyncio
async def test_constructor_validation(redis_client):
    with pytest.raises(ValueError):
        TokenBucket(refill_rate=0, capacity=0, redis_client=redis_client)

    with pytest.raises(ValueError):
        TokenBucket(refill_rate=-1, capacity=10, redis_client=redis_client)

    with pytest.raises(ValueError):
        TokenBucket(refill_rate=0, capacity=-1, redis_client=redis_client)
