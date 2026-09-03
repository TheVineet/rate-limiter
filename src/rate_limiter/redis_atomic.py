from redis.asyncio import Redis
import time
from typing import List


class TokenBucket:
    def __init__(
        self,
        redis_client: Redis,
        refill_rate: float = 1,
        capacity: float = 10,
        token_value: float = 1,
    ):
        self.redis_client = redis_client
        self.refill_rate = refill_rate
        self.capacity = capacity
        self.token_value = token_value

        if self.capacity <= 0:
            raise ValueError("Capacity should be more than 0")

        if self.refill_rate < 0:
            raise ValueError("Refill rate cannot be negative")

        with open("src/rate_limiter/scripts/token_bucket.lua", "r") as file:
            self.LUA_SCRIPT = file.read()

    async def consume(self, key: str):
        # key = KEYS[0]
        # refill_rate = ARGV[0]
        # capacity = ARGV[1]
        # timestamp = ARGV[2]
        # token_value = ARGV[3]

        # result =  [allowed,capacity,remaining,reset]

        now = time.monotonic()
        result: List = await self.redis_client.eval(
            self.LUA_SCRIPT,
            1,
            key,
            self.refill_rate,
            self.capacity,
            now,
            self.token_value,
        )

        return {
            "allowed": result[0],
            "capacity": result[1],
            "remaining": result[2],
            "reset": result[3],
        }
