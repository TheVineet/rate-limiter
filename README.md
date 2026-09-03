# Rate Limiter

A distributed rate limiter built from scratch to explore the trade-offs between **correctness, concurrency, and scalability** in production systems.

The project starts with a simple in-memory Token Bucket implementation, moves state into Redis, intentionally introduces a race condition, and then fixes it using an **atomic Redis Lua script**.

The goal isn't just to build a rate limiter that works — it's to understand **why a seemingly correct implementation can fail under concurrency**, and how distributed systems primitives can be used to fix it.

---

## What this demonstrates

- **Token Bucket algorithm** — capacity, refill rate, and controlled bursts
- **In-memory rate limiting** without external infrastructure
- **Distributed rate limiting** using Redis
- The race condition caused by naive **read → decide → write** operations
- Atomic state transitions using **Redis Lua scripting (`EVAL`)**
- Why Redis transactions such as `WATCH` / `MULTI` are less attractive under high contention
- **Per-client isolation** using API keys
- **Fail-open behavior** when Redis is unavailable
- FastAPI integration through a reusable rate-limiting decorator/dependency
- `X-RateLimit-*` response headers
- `429 Too Many Requests` responses
- Concurrency testing against a **real Redis instance**, rather than mocks

---

## Architecture

The project has three implementations of the Token Bucket algorithm:

```text
                         ┌─────────────────────┐
                         │     FastAPI App      │
                         │      app/main.py     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Rate Limit Decorator│
                         │ rate_limiter/decorator│
                         └──────────┬──────────┘
                                    │
                  ┌─────────────────┼─────────────────┐
                  │                 │                 │
                  ▼                 ▼                 ▼
           ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
           │  In-Memory  │  │ Redis Naive  │  │Redis Atomic │
           │ Token Bucket│  │ Token Bucket │  │ Token Bucket│
           └─────────────┘  └──────┬──────┘  └──────┬──────┘
                                   │                 │
                                   ▼                 ▼
                              Redis state      Redis + Lua
                                              atomic operation
```

The important distinction is between the two Redis implementations:

```text
Redis Naive

READ ──► DECIDE ──► WRITE
          ▲
          │
     Race condition
     under concurrency


Redis Atomic

        ┌──────────────────────┐
        │      Lua Script      │
        │                      │
READ ──►│  DECIDE ──► WRITE    │
        │                      │
        └──────────────────────┘
              atomic
```

---

## Evolution

The project deliberately evolves through several stages.

| Stage | Implementation                     | Purpose                                                                                  |
| ----- | ---------------------------------- | ---------------------------------------------------------------------------------------- |
| 1     | `src/rate_limiter/in_memory.py`    | Core Token Bucket logic without external infrastructure                                  |
| 2     | `src/rate_limiter/redis_naive.py`  | Moves state to Redis using a naive read/modify/write approach                            |
| 3     | `src/rate_limiter/redis_atomic.py` | Makes the Redis operation atomic using Lua                                               |
| 4     | `src/rate_limiter/decorator.py`    | Integrates rate limiting with FastAPI, including fail-open behavior and response headers |

The naive Redis implementation is **intentionally incorrect under concurrent access**. It is kept in the project to demonstrate the race condition and provide a baseline for comparison with the atomic implementation.

---

## Project Structure

```text
.
├── app/
│   └── main.py
│
├── docs/
│   └── RESEARCH.md
│
├── src/
│   ├── config.py
│   ├── redis_client.py
│   │
│   └── rate_limiter/
│       ├── decorator.py
│       ├── in_memory.py
│       ├── redis_naive.py
│       ├── redis_atomic.py
│       │
│       └── scripts/
│           └── token_bucket.lua
│
├── tests/
│   ├── conftest.py
│   ├── test_in_memory.py
│   ├── test_redis_naive.py
│   ├── test_redis_atomic.py
│   └── test_concurrency.py
│
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── README.md
```

---

## Running the Project

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker

### 1. Clone the repository

```bash
git clone https://github.com/TheVineet/rate-limiter.git
cd rate-limiter
```

### 2. Create the environment and install dependencies

```bash
uv sync
```

`uv` creates and manages the project's virtual environment based on `pyproject.toml` and `uv.lock`.

### 3. Start Redis

```bash
docker compose up -d
```

### 4. Run the FastAPI application

```bash
uv run uvicorn app.main:app --reload
```

The API will be available at:

```text
http://localhost:8000
```

---

## Example

A client can be identified using an API key:

```bash
curl \
  -H "X-API-Key: demo-key-1" \
  http://localhost:8000/some-endpoint
```

A successful request can return rate-limit metadata through response headers:

```text
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1699999999
```

When the bucket is exhausted:

```text
HTTP/1.1 429 Too Many Requests

Retry-After: 3
```

The exact endpoint depends on the FastAPI demo configuration in `app/main.py`.

---

## The Race Condition

The naive Redis implementation performs the rate-limit operation as separate steps:

```text
1. Read bucket state
2. Calculate whether a request should be allowed
3. Update bucket state
```

With concurrent requests, multiple workers can read the same state before any of them writes the updated value.

For example, with a bucket containing **3 tokens**:

```text
Request A ──► READ: 3 tokens
Request B ──► READ: 3 tokens
Request C ──► READ: 3 tokens
Request D ──► READ: 3 tokens

A ──► allow ──► WRITE: 2
B ──► allow ──► WRITE: 2
C ──► allow ──► WRITE: 2
D ──► allow ──► WRITE: 2
```

More than three requests can therefore be accepted even though the bucket capacity is three.

This is the classic **check-then-act race condition**.

---

## The Atomic Solution

The atomic implementation moves the entire operation into a Redis Lua script:

```text
┌────────────────────────────────────┐
│           Redis Lua Script         │
│                                    │
│  1. Read current state             │
│  2. Calculate token refill         │
│  3. Check available tokens         │
│  4. Consume token if allowed       │
│  5. Update state                   │
│  6. Return result                  │
│                                    │
└────────────────────────────────────┘
```

Redis executes the Lua script atomically, so another request cannot interleave itself between the read, decision, and update operations.

The script is located at:

```text
src/rate_limiter/scripts/token_bucket.lua
```

This allows the Token Bucket decision to remain atomic even when many requests arrive concurrently.

---

## Why Not `WATCH` / `MULTI`?

Redis transactions can also be used to protect a read-modify-write operation using optimistic locking:

```text
WATCH
  ↓
READ
  ↓
DECIDE
  ↓
MULTI
  ↓
WRITE
  ↓
EXEC
```

However, under high contention, concurrent writers can repeatedly invalidate each other's transactions, causing retries.

Lua provides a simpler model for this particular operation:

```text
Client
   │
   ▼
Single Redis command
   │
   ▼
Lua script
   │
   ├── read
   ├── calculate
   ├── decide
   └── write
```

The complete state transition happens inside Redis.

The reasoning and trade-offs are documented in [`docs/RESEARCH.md`](docs/RESEARCH.md).

---

## Failure Mode: Fail Open

Redis is infrastructure, not the API itself.

If Redis becomes unavailable, the rate limiter should not necessarily turn a healthy API into an outage.

This implementation therefore follows a **fail-open** strategy:

```text
Request
   │
   ▼
Rate Limiter
   │
   ├── Redis available ──► Enforce limit
   │
   └── Redis unavailable ─► Allow request
```

This means Redis failure can temporarily remove rate limiting, but it does not prevent the underlying API from serving requests.

This is a deliberate availability vs. protection trade-off.

---

## Identity

Rate limits are keyed by **API key** in this project.

For example:

```text
Client_A ──► rate-limit:Client_A
Client_B ──► rate-limit:Client_B
```

Exhausting one client's bucket does not affect another client.

API-key-based identity is particularly useful for B2B APIs where consumers are already authenticated through API credentials.

Other identity strategies such as IP address or user ID have different trade-offs and are discussed in [`docs/RESEARCH.md`](docs/RESEARCH.md).

---

## Testing

Run the complete test suite with:

```bash
uv run pytest tests/ -v
```

The tests cover:

- Token Bucket initialization and validation
- Token consumption
- Token refill behavior
- Capacity boundaries
- Exact allow/reject transitions
- Client isolation
- Redis-backed rate limiting
- **Concurrent requests against real Redis**
- Race-condition behavior in the naive implementation
- Atomic behavior of the Lua implementation

### Concurrency Test

The most important test is the concurrency comparison.

For a bucket with:

```text
capacity = 3
refill_rate = 0
```

100 concurrent requests are sent.

The naive implementation demonstrates the race condition:

```text
Naive implementation
100 concurrent requests
        ↓
More than 3 requests can be allowed
```

The atomic implementation enforces the limit:

```text
Atomic implementation
100 concurrent requests
        ↓
Exactly 3 requests are allowed
```

The concurrency tests use a real Redis instance rather than mocking Redis, so the test exercises the actual Redis behavior and Lua execution path.

---

## Research

The [`docs/RESEARCH.md`](docs/RESEARCH.md) contains the deeper reasoning behind the implementation, including:

- Rate-limiting algorithms
- Token Bucket vs. other algorithms
- Distributed rate limiting
- Redis consistency and race conditions
- Atomic operations
- Lua scripting
- `WATCH` / `MULTI-EXEC`
- Failure-mode considerations
- How large-scale systems approach rate limiting

The code is intentionally paired with the research so that the implementation explains the concepts rather than simply providing a finished solution.

---

## Tech Stack

- **Python**
- **FastAPI**
- **Redis**
- **Redis Lua scripting / `EVAL`**
- **pytest**
- **pytest-asyncio**
- **Docker / Docker Compose**
- **uv**

---

## Project Goal

This is primarily a learning and engineering exercise.

Rather than treating rate limiting as a simple counter:

```text
if requests > limit:
    reject()
```

the project explores what happens when rate limiting becomes a **distributed systems problem**:

> How do you maintain a correct shared state when multiple requests can modify that state concurrently?

The final implementation uses Redis + Lua to make that state transition atomic while keeping the rate limiter independent from the API's core business logic.
