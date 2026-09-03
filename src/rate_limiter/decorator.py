import functools
from math import ceil
from fastapi import Request, HTTPException, Response
from src.rate_limiter.redis_atomic import TokenBucket
from src.redis_client import get_redis


def rate_limiter(
    bucket_capacity: float = 10,
    refill_rate: float = 1,
    api_cost: float = 1,
    trust_proxy_headers: bool = False,
):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper_function(*args, **kwargs):
            request: Request = kwargs.get("request") or next(
                (a for a in args if isinstance(a, Request)), None
            )
            if request is None:
                raise RuntimeError(
                    f"@rate_limiter requires 'request:Request' as a parameter in {func.__name__}"
                )

            injected_response: Response = kwargs.get("response") or next(
                (a for a in args if isinstance(a, Response)), None
            )

            # Key extraction — no Redis involved, keep it outside the try
            api_key = request.headers.get("X-API-Key")
            if api_key:
                import hashlib

                key = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            elif trust_proxy_headers:
                forwarded_for = request.headers.get("X-Forwarded-For")
                if forwarded_for:
                    key = forwarded_for.split(",")[0].strip()
                else:
                    real_ip = request.headers.get("X-Real-IP")
                    key = real_ip if real_ip else request.client.host
            else:
                key = request.client.host

            try:
                redis_client = await get_redis()
                bucket = TokenBucket(
                    redis_client=redis_client,
                    capacity=bucket_capacity,
                    refill_rate=refill_rate,
                    token_value=api_cost,
                )
                result = await bucket.consume(key=key)
            except Exception:
                # Redis/setup itself failed — fail open, and stop here.
                return await func(*args, **kwargs)

            allowed = result.get("allowed", True)
            capacity = result.get("capacity")
            remaining = result.get("remaining")
            reset = result.get("reset")

            if not allowed:
                tokens_needed = api_cost - remaining
                retry_after = (
                    ceil(tokens_needed / refill_rate) if refill_rate > 0 else -1
                )
                headers = {
                    "X-RateLimit-Limit": str(capacity),
                    "X-RateLimit-Remaining": str(remaining),
                    "X-RateLimit-Reset": str(reset),
                }
                if retry_after > 0:
                    headers["Retry-After"] = str(retry_after)
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Too many requests. Try after {retry_after} seconds"
                        if retry_after > 0
                        else "Too many requests"
                    ),
                    headers=headers,
                )

            result = await func(*args, **kwargs)
            if injected_response is not None:
                injected_response.headers["X-RateLimit-Limit"] = str(capacity)
                injected_response.headers["X-RateLimit-Remaining"] = str(remaining)
                injected_response.headers["X-RateLimit-Reset"] = str(reset)
            return result

        return wrapper_function

    return decorator
