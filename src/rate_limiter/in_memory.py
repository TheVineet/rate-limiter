from typing import Dict
import time
import random


class TokenBucket:
    # db = {key1 : {"tokens" : value, "last_refill_timestamp" : value}, key2 : {} ...}
    # refill rate = tokens/second
    # capacity = int

    def __init__(self, refill_rate: int = 1, capacity: int = 10):
        if refill_rate < 0:
            raise ValueError("Refill rate cant be negative")
        if capacity <= 0:
            raise ValueError("Capacity should be more than 0")
        self.refill_rate = refill_rate
        self.capacity = capacity
        self.db = {}

    def consume(self, key: str):
        # Get the current tokens value for the key
        key_val: Dict = self.db.get(key)
        now = time.monotonic()
        if key_val is None:
            # initialisation
            key_val = {"tokens": self.capacity, "last_refill_timestamp": now}
            self.db[key] = key_val

        tokens = key_val.get("tokens")
        last_refill_timestamp = key_val.get("last_refill_timestamp")

        interval = now - last_refill_timestamp

        refilled_amount = interval * self.refill_rate

        tokens = min(tokens + refilled_amount, self.capacity)

        key_val["last_refill_timestamp"] = now

        if tokens >= 1:
            key_val["tokens"] = tokens - 1
            return True

        else:
            key_val["tokens"] = tokens
            return False
