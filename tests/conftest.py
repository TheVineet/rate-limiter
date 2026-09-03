import pytest
import redis.asyncio as aioredis
from src.config import settings


@pytest.fixture
async def redis_client():
    client = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
    )

    await client.flushdb()
    # Cleanup

    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()
