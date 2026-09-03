import redis.asyncio as aioredis
from src.config import settings

redis_client = aioredis.Redis(
    host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB
)


async def get_redis():
    return redis_client
