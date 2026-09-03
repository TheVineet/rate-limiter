from src.rate_limiter.in_memory import TokenBucket
from unittest.mock import patch
import pytest


def test_rejects_when_bucket_is_empty():
    bucket = TokenBucket(refill_rate=0, capacity=3)
    assert bucket.consume("Client_A") is True
    assert bucket.consume("Client_A") is True
    assert bucket.consume("Client_A") is True
    assert bucket.consume("Client_A") is False


def test_refill_all_after_empty():
    mock_time = 100.0

    with patch("time.monotonic", side_effect=lambda: mock_time):
        bucket = TokenBucket(refill_rate=1, capacity=3)
        assert bucket.consume("Client_A") is True
        assert bucket.consume("Client_A") is True
        assert bucket.consume("Client_A") is True
        assert bucket.consume("Client_A") is False  # Bucket is now empty

        mock_time += 1  # Fast forward by 1 second

        assert bucket.consume("Client_A") is True  # 1 Token refilled
        assert bucket.consume("Client_A") is False  # Bucket is empty again


def test_never_exceed_capacity():
    mock_time = 100.0
    with patch("time.monotonic", side_effect=lambda: mock_time):
        bucket = TokenBucket(refill_rate=100, capacity=3)
        mock_time += 100  # Fast forward 100 seconds

        assert bucket.consume("Client_A") is True
        assert bucket.consume("Client_A") is True
        assert bucket.consume("Client_A") is True

        assert bucket.consume("Client_A") is False  # Bucket is now empty


def test_client_isolation():
    bucket = TokenBucket(refill_rate=0, capacity=3)
    assert bucket.consume("Client_A") is True
    assert bucket.consume("Client_A") is True
    assert bucket.consume("Client_A") is True
    assert bucket.consume("Client_A") is False

    assert bucket.consume("Client_B") is True
    assert bucket.consume("Client_B") is True
    assert bucket.consume("Client_B") is True
    assert bucket.consume("Client_B") is False


def test_constructor_validation():
    with pytest.raises(ValueError):
        TokenBucket(refill_rate=0, capacity=0)

    with pytest.raises(ValueError):
        TokenBucket(refill_rate=-1, capacity=10)

    with pytest.raises(ValueError):
        TokenBucket(refill_rate=0, capacity=-1)
