from src.rate_limiter.redis_naive import TokenBucket
import time
from unittest.mock import patch
import pytest


@pytest.mark.asyncio
async def test_rejects_when_bucket_is_empty(redis_client):
    bucket = TokenBucket(refill_rate=0, capacity=3, redis_client=redis_client)
    assert await bucket.consume("Client_A") is True
    assert await bucket.consume("Client_A") is True
    assert await bucket.consume("Client_A") is True
    assert await bucket.consume("Client_A") is False


@pytest.mark.asyncio
async def test_refill_all_after_empty(redis_client):
    mock_time = 100.0

    with patch("time.monotonic", side_effect=lambda: mock_time):
        bucket = TokenBucket(refill_rate=1, capacity=3, redis_client=redis_client)
        assert await bucket.consume("Client_A") is True
        assert await bucket.consume("Client_A") is True
        assert await bucket.consume("Client_A") is True
        assert await bucket.consume("Client_A") is False  # Bucket is now empty

        mock_time += 1  # Fast forward by 1 second

        assert await bucket.consume("Client_A") is True  # 1 Token refilled
        assert await bucket.consume("Client_A") is False  # Bucket is empty again


@pytest.mark.asyncio
async def test_never_exceed_capacity(redis_client):
    mock_time = 100.0
    with patch("time.monotonic", side_effect=lambda: mock_time):
        bucket = TokenBucket(refill_rate=100, capacity=3, redis_client=redis_client)
        mock_time += 100  # Fast forward 100 seconds

        assert await bucket.consume("Client_A") is True
        assert await bucket.consume("Client_A") is True
        assert await bucket.consume("Client_A") is True

        assert await bucket.consume("Client_A") is False  # Bucket is now empty


@pytest.mark.asyncio
async def test_client_isolation(redis_client):
    bucket = TokenBucket(refill_rate=0, capacity=3, redis_client=redis_client)
    assert await bucket.consume("Client_A") is True
    assert await bucket.consume("Client_A") is True
    assert await bucket.consume("Client_A") is True
    assert await bucket.consume("Client_A") is False

    assert await bucket.consume("Client_B") is True
    assert await bucket.consume("Client_B") is True
    assert await bucket.consume("Client_B") is True
    assert await bucket.consume("Client_B") is False


@pytest.mark.asyncio
async def test_constructor_validation(redis_client):
    with pytest.raises(ValueError):
        TokenBucket(refill_rate=0, capacity=0, redis_client=redis_client)

    with pytest.raises(ValueError):
        TokenBucket(refill_rate=-1, capacity=10, redis_client=redis_client)

    with pytest.raises(ValueError):
        TokenBucket(refill_rate=0, capacity=-1, redis_client=redis_client)
