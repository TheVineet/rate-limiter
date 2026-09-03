from fastapi import FastAPI, Request, Response
from src.rate_limiter.decorator import rate_limiter

app = FastAPI()


@app.get("/test")
@rate_limiter(bucket_capacity=3, refill_rate=1, api_cost=1, trust_proxy_headers=False)
async def get(request: Request, response: Response):
    return "You are allowed"
