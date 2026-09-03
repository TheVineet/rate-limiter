from redis.asyncio import Redis
import time


class TokenBucket:
    def __init__(self, redis_client: Redis, refill_rate=1, capacity=10, token_value=1):
        self.redis_client = redis_client
        self.refill_rate = refill_rate
        self.capacity = capacity
        self.token_value = token_value

        if self.refill_rate < 0:
            raise ValueError("Refill rate cannot be negative")
        if self.capacity <= 0:
            raise ValueError("Capacity cannot be less than or equal to 0")

    async def consume(self, key: str):
        # Get the bucket
        now = time.monotonic()
        token = await self.redis_client.hget(name=key, key="token")
        if token is None:
            token = self.capacity
            await self.redis_client.hset(name=key, key="token", value=token)
        else:
            token = token.decode()

        token = float(token)

        last_read_timestamp = await self.redis_client.hget(
            name=key, key="last_read_timestamp"
        )

        if last_read_timestamp is None:
            last_read_timestamp = now
            await self.redis_client.hset(
                name=key, key="last_read_timestamp", value=last_read_timestamp
            )
        else:
            last_read_timestamp = last_read_timestamp.decode()

        last_read_timestamp = float(last_read_timestamp)

        interval: float = now - last_read_timestamp  # in seconds

        refill_amount = interval * self.refill_rate

        token = min(token + refill_amount, self.capacity)
        await self.redis_client.hset(name=key, key="last_read_timestamp", value=now)

        if token >= self.token_value:
            # request goes through
            token = token - self.token_value
            await self.redis_client.hset(name=key, key="token", value=token)
            return True

        else:
            # request fails
            return False
