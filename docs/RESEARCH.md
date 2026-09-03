There must be so many documents and articles about RateLimiter on the internet. But in this document, I would mainly focus on answering few questions. And then we will look at some examples on how some other big companies are implementing the rate limiter.
We would also discuss various rate limiting algorithms and also various forms of rate limiters and load shedding.

### Lets Get Started

### 1. Why Do We Need Rate Limiting?

A company has finite resources, whether it is a small startup or a large-scale technology company. It is therefore undesirable for a single user, client, or source to consume a disproportionately large amount of those resources compared with other users.

If one client starts making an excessive number of requests, intentionally or unintentionally, it can consume resources such as CPU, memory, database connections, network bandwidth, or downstream-service capacity. As a result, other users may experience higher latency, errors, or degraded performance.

**Rate limiting** is a mechanism used to control how frequently a client is allowed to perform an operation within a given period of time.

Since APIs are one of the primary ways clients interact with backend systems, rate limiting is commonly expressed as a restriction on the number of requests a user, client, IP address, device, or other source can make to an API within a particular time period.

For example:

> A client may make at most 100 requests per minute to an API.

This helps prevent a single source from disproportionately consuming shared system resources and helps maintain predictable service for other users.

Rate limiting can also be useful during periods of unusually high load or degraded system capacity. For example, a system may restrict lower-priority traffic while continuing to serve critical operations. This allows the system to protect important functionality instead of allowing excessive demand to affect the entire service.

Therefore, rate limiting is not only about preventing malicious abuse. It can also be used as a mechanism for **protecting system resources, controlling traffic, and maintaining availability and a consistent experience for users**.

---

## Core Idea and Implementation

Since every request would pass through the rate limiter, the rate limiter itself needs to be extremely fast. A common choice for storing rate-limiting state is an **in-memory data store such as Redis**.

Redis is well suited for rate limiting because it provides very fast reads and writes, supports atomic operations such as `INCR`, and provides key expiration through commands such as `EXPIRE` and `PEXPIRE`. Commands such as `TTL` and `PTTL` can be used to check the remaining lifetime of an expiring key.

There are several commonly discussed approaches to rate limiting. In this research, we will focus on the following five:

| Algorithm                  | Redis Structure    | Memory per Client | Accuracy    | Burst Behavior                              | Best Suited For                       |
| -------------------------- | ------------------ | ----------------: | ----------- | ------------------------------------------- | ------------------------------------- |
| **Fixed Window Counter**   | String + Lua       |             1 key | Approximate | Can allow up to ~2× the limit at boundaries | Simple API limits, login throttling   |
| **Sliding Window Log**     | Sorted Set + Lua   |      O(n) entries | Exact       | Prevents fixed-window boundary bursts       | High-value APIs, audit trails         |
| **Sliding Window Counter** | 2 Strings + Lua    |            2 keys | Approximate | Smoother boundaries                         | General-purpose API rate limiting     |
| **Token Bucket**           | Hash + Lua         |  1 key / 2 fields | Exact model | Allows controlled bursts                    | Bursty traffic with average-rate caps |
| **Leaky Bucket**           | Hash + Lua / Queue |    1 key or queue | Exact model | Smooth output for shaping                   | Traffic shaping or policing           |

### 1. Fixed Window Counter

The main idea behind the **Fixed Window Counter** is to divide time into fixed-length intervals called **windows**.

For example, if the limit is 100 requests per minute:

```text
00:00 ───────────── 01:00 ───────────── 02:00
       Window 1             Window 2
```

Whenever a request arrives, we determine which window the request belongs to and check the counter for that window.

If the counter is below the allowed limit, we allow the request and increment the counter by 1.

If the counter has already reached the limit, we reject the request.

For example:

```text
Limit = 100 requests/minute

Request 1   → counter = 1   → ALLOW
Request 2   → counter = 2   → ALLOW
...
Request 100 → counter = 100 → ALLOW
Request 101 → counter = 100 → REJECT
```

A major advantage of the Fixed Window Counter is its simplicity. It requires very little state — typically **one counter key per client per window**.

For example:

```text
rate_limit:user_123:window_42 → 57
```

The key can also have an expiration corresponding to the end of the window.

However, Fixed Window Counter has a significant drawback: **boundary bursts**.

Consider a limit of 100 requests per minute:

```text
             01:00
               │
Window 1       │       Window 2
───────────────│───────────────
       100     │     100
    requests   │   requests
```

A client could send 100 requests just before `01:00` and another 100 requests immediately after `01:00`.

This means that although the configured limit is 100 requests per minute, the system could receive almost **200 requests within a very short period around the boundary**.

Therefore, Fixed Window Counter is simple and efficient, but it does not provide a smooth representation of the request rate.

---

### 2. Sliding Window Log

The **Sliding Window Log** addresses the boundary-burst problem of the Fixed Window Counter.

Instead of dividing time into globally fixed windows, every request is recorded with its timestamp.

For every incoming request, we consider the time range:

```text
(current_timestamp - window_duration, current_timestamp]
```

and count how many requests from that client occurred during that period.

For example, with a limit of 100 requests per minute:

```text
        ←────── 60 seconds ──────→
       oldest                    now
         │                         │
         ▼                         ▼
─────────●────●──●────●────●───────●
       requests inside window
```

If the number of requests inside the sliding window is below the limit, the new request is allowed and its timestamp is recorded.

If the number has already reached the limit, the request is rejected.

Redis Sorted Sets are well suited for this approach because they allow us to associate each request with a timestamp score.

Conceptually:

```text
Sorted Set

request-A → 1000
request-B → 1012
request-C → 1027
request-D → 1041
```

When a request arrives, old entries outside the sliding window can be removed, and the remaining entries can be counted.

The major advantage of the Sliding Window Log is that it **solves the fixed-window boundary-burst problem** because the window continuously moves with time.

The major disadvantage is **memory usage**.

Because every request needs to be stored for the duration of the window, the amount of storage grows with the number of requests.

For example, if the rate limit is:

```text
10,000 requests/hour
```

then potentially up to 10,000 request entries may need to be stored for a single client during that hour.

Therefore, Sliding Window Log provides accurate request counting but can become expensive in terms of memory and storage at high request rates.

---

### 3. Sliding Window Counter

The **Sliding Window Counter** attempts to solve two problems:

1. The boundary-burst problem of the Fixed Window Counter.
2. The storage problem of the Sliding Window Log.

Like Fixed Window Counter, we still divide time into fixed windows and maintain counters for those windows.

However, instead of considering only the current window, we use the counter from the previous window to **estimate how many requests fall inside the current sliding window**.

For example, suppose the window duration is one hour and the current time is 15 minutes into the current window:

```text
Previous Window       Current Window
──────────────────│──────────────────
                  │
                  │←── 15 min ──→
                  │
                  now
```

At this point, approximately 75% of the previous window overlaps with the current sliding window.

Therefore, the estimated number of requests in the current sliding window can be calculated as:

```text
estimated_count =
    previous_window_count * 0.75
    + current_window_count
```

More generally:

```text
estimated_count =
    previous_window_count * overlap_ratio
    + current_window_count
```

If the estimated count is below the configured limit, the request is allowed and the current-window counter is incremented.

Otherwise, the request is rejected.

The major advantage of the Sliding Window Counter is that it requires significantly less storage than the Sliding Window Log. Instead of storing every request, we only need counters for the relevant windows.

It also provides a smoother approximation of the request rate and reduces the boundary-burst problem of the Fixed Window Counter.

The main disadvantage is that the count is **an approximation rather than an exact count**, because the algorithm assumes that requests from the previous window were distributed relatively evenly throughout that window.

---

### 4. Token Bucket

The **Token Bucket** is one of the most widely used approaches for rate limiting.

The main idea is that every client has a bucket containing tokens.

Tokens are continuously added to the bucket at a configured **refill rate**, up to a maximum **bucket capacity**.

For example:

```text
Bucket capacity = 10 tokens
Refill rate     = 2 tokens/second
```

A request consumes one or more tokens.

If the bucket contains enough tokens, the request is allowed and the required number of tokens are removed.

If there are not enough tokens, the request is rejected.

Conceptually:

```text
                 refill
                   ↓
            ┌─────────────┐
            │   10 tokens │  ← capacity
            │             │
            └──────┬──────┘
                   │
                request
                   │
              consume token
                   │
                   ▼
                ALLOW
```

The two important parameters are:

- **Bucket capacity** — determines how large a burst can be.
- **Refill rate** — determines the long-term average rate at which requests can be accepted.

For example:

```text
capacity   = 10 requests
refill     = 2 requests/second
```

A client with a full bucket could immediately make up to 10 requests, allowing a controlled burst. After that, tokens are replenished at 2 tokens per second.

The major advantage of Token Bucket is therefore its ability to **allow controlled bursts while still enforcing an average rate**.

It is particularly useful when short bursts of traffic are acceptable but sustained high traffic should be limited.

We will use the Token Bucket algorithm extensively in our rate-limiter implementation.

---

### 5. Leaky Bucket

The **Leaky Bucket** is similar to Token Bucket in that it controls the rate at which traffic is processed, but its behavior is different.

There are two common ways to think about Leaky Bucket:

1. **Leaky Bucket as a queue — traffic shaping**
2. **Leaky Bucket as a meter — traffic policing**

#### 5.1 Leaky Bucket as a Queue — Shaping

Incoming requests are placed into a FIFO queue.

A scheduler then removes requests from the queue at a fixed rate.

For example:

```text
Incoming requests
       │
       ▼
┌──────────────┐
│ FIFO Queue   │
│              │
│ Request A    │
│ Request B    │
│ Request C    │
└──────┬───────┘
       │
       │ fixed-rate drain
       ▼
    Request A
       │
       ▼
    Request B
       │
       ▼
    Request C
```

If the queue is full, new requests are rejected.

The important characteristic of this approach is that accepted requests may be **delayed**.

Even if 20 requests arrive simultaneously, they are forwarded at the configured fixed rate rather than being forwarded as a burst.

Therefore, this approach is useful when we want to **smooth the outgoing traffic**.

---

#### 5.2 Leaky Bucket as a Meter — Policing

In the policing version, we don't necessarily queue and delay requests.

Instead, we maintain a level representing how much traffic has accumulated.

The level drains at a fixed rate.

When a request arrives, we determine whether accepting it would cause the level to exceed the bucket's capacity.

```text
Incoming request
       │
       ▼
Would accepting it exceed capacity?
       │
   ┌───┴────┐
   │        │
  YES       NO
   │        │
   ▼        ▼
REJECT    ACCEPT
```

Accepted requests are passed through immediately; they are not delayed.

Therefore:

- **Shaping** → delay requests and release them at a controlled rate.
- **Policing** → reject requests that exceed the allowed level.

The main characteristic of Leaky Bucket shaping is that it produces a **smooth, predictable output rate**, whereas Token Bucket intentionally allows controlled bursts.

---

## Rate Limiters, the Stripe Way

At Stripe, they use **four different types of rate limiting and load shedding mechanisms**. We can think of these as four lines of defense, where each layer protects the system from a different kind of overload.

### 1. Request Rate Limiter

This is the first level of protection at Stripe.

It limits the number of requests a user can make within a given period of time.

For example:

```text
100 requests / second / user
```

If a user exceeds the configured limit, subsequent requests can be rejected.

This protects the system from clients generating an unusually high request rate.

---

### 2. Concurrent Requests Limiter

A request-rate limiter does not necessarily protect against requests that are individually expensive or take a long time to complete.

For example, an endpoint might perform CPU-intensive work or take a significant amount of time to finish. Even if the client is sending requests at an acceptable rate, many of those requests could remain in progress simultaneously and consume a large amount of system resources.

The concurrent requests limiter therefore limits the number of requests that a client can have **in progress at the same time**.

For example:

```text
Maximum concurrent requests = 10

Request 1  → in progress
Request 2  → in progress
...
Request 10 → in progress

Request 11 → rejected / delayed
```

This is particularly useful for protecting CPU-intensive or otherwise expensive endpoints.

---

### 3. Fleet Usage Load Shedder

The previous two mechanisms operate at the level of individual clients or requests.

The **Fleet Usage Load Shedder** protects the service at the fleet level.

The basic idea is to reserve a portion of the available fleet capacity for critical traffic.

For example, suppose a service has 100 units of capacity and wants to reserve 20% for critical endpoints:

```text
Total fleet capacity
────────────────────────────────────

Critical traffic       Other traffic
      20%                   80%
      ↓                      ↓
 reserved                 available
```

If non-critical traffic starts consuming too much of the fleet, the load shedder can begin rejecting non-critical requests so that the reserved capacity remains available for critical operations.

This provides protection against situations where excessive traffic from one part of the system could otherwise consume resources needed by more important operations.

---

### 4. Worker Utilisation Load Shedder

This is another layer of protection that operates closer to the individual workers handling requests.

Most API services use a set of workers to process requests. If those workers become heavily loaded, the system can start rejecting lower-priority traffic before the workers become completely overwhelmed.

At Stripe, traffic is classified into four categories:

1. **Critical methods**
2. **POST methods**
3. **GET methods**
4. **Test-mode traffic**

When worker utilisation becomes sufficiently high, lower-priority traffic can be shed first.

Therefore, traffic is progressively protected according to priority, with **test-mode traffic being shed before higher-priority traffic**.

The overall idea is:

```text
Worker becomes increasingly loaded
                │
                ▼
       Start shedding traffic
                │
                ▼
       Test-mode traffic
                │
                ▼
          GET traffic
                │
                ▼
         POST traffic
                │
                ▼
       Critical methods
```

The goal is not simply to reject requests. The goal is to ensure that **important operations continue functioning even when the system is under significant load**.

---

## Important Things to Consider When Implementing Rate Limiters

### 1. Hook the Rate Limiter into the Middleware Stack Safely

A rate limiter should not become a new single point of failure for the API.

For example, if the rate limiter depends on Redis and Redis becomes unavailable, we need to decide what should happen to incoming requests.

A particularly important consideration is **failing open**: if the rate limiter encounters an unexpected coding or operational error, the API should continue operating rather than accidentally blocking all traffic.

Therefore, rate-limiting code should be designed so that failures in the limiter itself do not unnecessarily take down the API.

---

### 2. Return Clear Responses to Users

When a request is rejected because of rate limiting or load shedding, the API should communicate the reason clearly.

For rate limiting, **HTTP 429 — Too Many Requests** is commonly used.

Depending on the situation, **HTTP 503 — Service Unavailable** may also be appropriate when the system is temporarily unable to serve requests because of capacity or overload.

It is also useful to provide rate-limit information through response headers, such as:

```text
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
```

These can communicate:

- The configured limit.
- How much capacity remains.
- When the limit will reset.

A `Retry-After` header can also be useful when the client should retry after a particular period.

---

### 3. Build Safeguards and a Kill Switch

Rate limiters themselves can contain bugs or be configured incorrectly.

Therefore, the system should have a way to **disable or modify the rate limiter quickly** without requiring a complete application deployment.

Useful operational safeguards include:

- A kill switch to disable the limiter.
- Metrics showing how frequently limits are triggered.
- Alerts for unusual rejection rates.
- Monitoring for errors from the rate-limiting infrastructure.
- The ability to change thresholds when necessary.

The goal is to ensure that a misconfigured or malfunctioning limiter does not become a cause of an outage.

---

### 4. Dark Launch the Rate Limiter

Before actually rejecting requests, we can run the rate limiter in a **dark-launch mode**.

In this mode, the limiter evaluates every request but does not actually block it.

Instead, we collect information about:

```text
Which requests would have been rejected?
Which users would have been affected?
How frequently would the limit have triggered?
```

This allows us to evaluate whether the chosen threshold is appropriate before enforcing it.

For example:

```text
Normal traffic
      │
      ▼
Rate limiter evaluates request
      │
      ├── Would allow → allow
      │
      └── Would reject → still allow
                           │
                           ▼
                       record metric
```

We can then use the collected data to choose thresholds that protect the API while minimizing the impact on legitimate customers and their existing usage patterns.

Dark launching is therefore an important way to validate a rate-limiting policy **before making it part of the request's enforcement path**.

## Rate Limiter Challenges

### 1. Race Conditions

Race conditions can occur when multiple requests concurrently access and modify the same rate-limit state.

For example, suppose the current counter is `9` and the limit is `10`. Two requests arrive at approximately the same time:

```text
              Counter = 9
                 │
        ┌────────┴────────┐
        ▼                 ▼
    Request A          Request B
        │                 │
     READ 9            READ 9
        │                 │
     + 1 = 10          + 1 = 10
        │                 │
     WRITE 10          WRITE 10
```

Both requests observed the same initial value. Both therefore conclude that the request should be allowed, even though only one additional request should have been accepted.

This is a **check-then-act / TOCTOU-style race condition**: the state can change between the time we inspect it and the time we act on that information.

For a rate limiter, the check and the state update therefore need to happen atomically.

Redis provides several mechanisms that can be used to coordinate these operations.

---

#### 1.1 `MULTI/EXEC`

Redis transactions using `MULTI/EXEC` queue multiple commands and execute them as an atomic batch. Other clients cannot interleave commands between the commands in the transaction.

However, `MULTI/EXEC` has an important limitation for rate limiting.

Consider the logic we actually need:

```text
READ counter
      ↓
Is counter < limit?
      ↓
YES → increment counter
      ↓
ALLOW
```

The decision depends on the value that was read.

With `MULTI/EXEC`, commands are queued before they execute, so we cannot naturally perform arbitrary conditional logic based on the result of an earlier command inside the transaction.

Therefore, while `MULTI/EXEC` provides atomic execution of a sequence of commands, it is not by itself a convenient way to implement a conditional rate-limit decision.

---

#### 1.2 `WATCH` + `MULTI/EXEC`

`WATCH` provides **optimistic concurrency control**.

The basic flow is:

```text
WATCH key
   ↓
READ counter
   ↓
Build transaction based on counter
   ↓
MULTI
   ↓
INCR / other commands
   ↓
EXEC
```

If another client modifies a watched key between the `WATCH` and `EXEC`, Redis aborts the transaction. The client then has to read the state again and retry.

This solves the race condition, but introduces another problem for a highly contended rate-limit key.

Imagine thousands of requests all trying to update the same counter:

```text
Request A ─┐
Request B ─┤
Request C ─┤
Request D ─┼──→ same key
Request E ─┤
Request F ─┘
```

Many clients can detect that the key changed and have their transactions aborted.

They then need to retry.

Therefore, as contention increases:

```text
more contention
      ↓
more transaction aborts
      ↓
more retries
      ↓
more work
```

This can make `WATCH` + `MULTI/EXEC` unattractive for a highly contended rate-limit counter.

---

#### 1.3 Lua Scripts with `EVAL`

Redis Lua scripts provide a much more convenient solution for this particular problem.

A Lua script executes on the Redis server, and Redis executes the script atomically with respect to other Redis commands. This means that the read, decision, and update can all happen together.

For example:

```text
GET counter
    ↓
if counter < limit then
    INCREMENT counter
    return ALLOW
else
    return REJECT
end
```

The important difference is that the conditional logic executes **inside Redis**, rather than requiring the client to:

1. Read the value.
2. Send the value back to the application.
3. Make a decision.
4. Send another command to Redis.

It can all happen in one server-side operation.

This also avoids the optimistic-concurrency retry loop associated with `WATCH`.

Therefore, for our rate limiter, Lua gives us:

- Atomic read → decision → update.
- Conditional logic.
- A single round trip between the application and Redis.
- No client-side retry loop caused by concurrent modifications.

### Lua Trade-offs

Lua is not free of trade-offs.

#### 1. Blocking Redis

Redis executes Lua scripts atomically, which means other Redis commands cannot execute while a script is running.

Therefore, rate-limiting scripts should be:

- Short.
- Deterministic.
- Free from expensive operations.
- Designed to perform only the necessary work.

A poorly designed Lua script could block the Redis event loop and affect unrelated Redis operations.

For our rate limiter, the script should essentially perform a small amount of state manipulation and return the decision.

---

#### 2. Redis Cluster Hash-Slot Constraints

Redis Cluster distributes keys across multiple hash slots.

A Lua script that accesses multiple keys needs those keys to be located in the **same hash slot**.

This matters for algorithms such as Sliding Window Counter, which may maintain state in two keys:

```text
previous_window_key
current_window_key
```

We can use Redis **hash tags** to force related keys into the same slot.

For example:

```text
rate_limit:{user_123}:previous
rate_limit:{user_123}:current
```

Because both keys contain `{user_123}`, Redis hashes the same portion of the key and places both keys in the same hash slot.

Single-key algorithms such as a simple Fixed Window Counter or Token Bucket don't have this particular multi-key issue.

---

#### 3. Debugging and Operational Complexity

Lua scripts move part of the application logic into Redis.

This can make the system slightly harder to debug because errors in the script are returned as Redis errors rather than occurring directly in the application code.

Therefore, Lua scripts should be:

- Kept small.
- Version controlled alongside the application.
- Tested independently.
- Tested against a real Redis instance before deployment.

---

### 2. Synchronization in a Distributed Environment

Solving race conditions on a **single rate limiter instance** is only part of the problem.

In a distributed system, we may have multiple application or rate-limiter instances:

```text
                    Load Balancer
                  /       |       \
                 ▼        ▼        ▼
              Server A Server B Server C
                 │        │        │
                 └────────┼────────┘
                          │
                       Redis
```

Suppose the rate limit is:

```text
100 requests / minute / user
```

User A sends requests to multiple servers:

```text
User A
  │
  ├── Request 1 → Server A
  ├── Request 2 → Server B
  ├── Request 3 → Server C
  ├── Request 4 → Server A
  └── ...
```

If every server maintains its own local counter:

```text
Server A → User A = 40
Server B → User A = 35
Server C → User A = 30
```

then the actual total is:

```text
40 + 35 + 30 = 105
```

The configured limit was only 100, but each server independently believed that the client was within its local limit.

This is the **synchronization problem**.

We therefore need some mechanism that allows multiple rate-limiter instances to share enough state to enforce the intended limit.

---

### Centralized State

The simplest solution is to use a shared data store such as Redis:

```text
                ┌─────────┐
                │  Redis  │
                └────┬────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
    Server A      Server B      Server C
```

Now every server checks and updates the same rate-limit state.

This gives us a consistent view of the counter and solves the problem of each server independently allowing its own quota.

However, this introduces a new bottleneck.

If **every request** must synchronously communicate with Redis:

```text
Request
   ↓
Rate limiter
   ↓
Redis
   ↓
Decision
   ↓
Application
```

then Redis becomes part of the request's critical path.

At very high request volumes, the centralized store itself can become a scalability constraint.

This leads to an important distributed-systems question:

> **Do we really need to synchronously update and read a centralized counter for every request?**

Cloudflare's architecture provides an interesting answer to this problem.

---

## 3. Cloudflare: Separating Counting from Enforcement

Cloudflare faced this problem at a much larger scale.

Their rate-limiting system needed to handle very large Layer 7 attacks, and they found that querying Memcached to obtain the current rate on every request would both put significant pressure on the Memcached cluster and add latency to legitimate requests.

Instead, Cloudflare separated the system into two conceptual paths:

```text
                 REQUEST PATH
                      │
                      ▼
              Local mitigation state
                      │
                      ▼
                ALLOW / MITIGATE


                COUNTING PATH
                      │
                      ▼
             Asynchronous increment
                      │
                      ▼
                  Memcached
                      │
                      ▼
             Threshold exceeded?
                      │
                      ▼
             Mitigation information
```

### Asynchronous Counting

Instead of making the request wait for the counting operation, Cloudflare runs the increment jobs asynchronously.

Therefore, the request does not need to perform an expensive centralized rate query before continuing.

Cloudflare describes this explicitly: the increment jobs are asynchronous, and when the request rate exceeds the threshold, another piece of data is stored instructing servers in the PoP to begin mitigation for that client.

This creates an important separation:

```text
Counting / Aggregation
        │
        │ asynchronous
        ▼
Centralized state


Request Decision
        │
        │ fast/local
        ▼
ALLOW / MITIGATE
```

The request path therefore does **not** need to calculate the complete current request rate on every request.

Instead, it only needs to know whether the client is currently under mitigation.

---

### Local Mitigation State

Cloudflare takes this optimization further.

Once a server learns that a particular client is being mitigated, it knows when that mitigation will end.

Therefore, the server can cache the mitigation information in its own memory.

For example:

```text
Server A memory:

Client A
    ↓
Mitigation active
    ↓
Expires at 12:05:00
```

Subsequent requests from Client A can then be handled using the local state:

```text
Client A
   │
   ▼
Server A
   │
   ▼
Local memory
   │
   ├── mitigation active → MITIGATE
   │
   └── expired → normal processing
```

Cloudflare states that once a server starts mitigating a client, it does not need to perform another query for subsequent requests from that source during the mitigation period.

This significantly reduces the amount of centralized coordination required during an attack.

---

### Why This Architecture Scales Better

A traditional centralized design might look like:

```text
Every request
     │
     ▼
Centralized Redis
     │
     ▼
count + decision
```

The centralized datastore therefore has to participate in essentially every request.

Cloudflare's approach is closer to:

```text
Every request
     │
     ▼
Local mitigation state
     │
     ▼
ALLOW / MITIGATE

       ↑
       │
 asynchronous
       │
       ▼
Centralized counting
```

The expensive counting and aggregation work is moved away from the synchronous request path.

This is particularly valuable during very large attacks, because putting a centralized datastore directly on the critical path could cause the rate limiter itself to become a bottleneck.

Cloudflare states that this final optimization allowed them to mitigate large Layer 7 attacks without noticeably penalizing legitimate requests.

---

## 4. The Distributed Rate Limiting Trade-off

Cloudflare's design demonstrates an important trade-off.

A centralized Redis-based limiter provides relatively straightforward shared state:

```text
Strong coordination
       ↓
Centralized state
       ↓
More consistent decisions
       ↓
Higher coordination cost
```

An architecture based on asynchronous counting and local enforcement reduces coordination:

```text
Less synchronous coordination
       ↓
Local decisions
       ↓
Lower request-path overhead
       ↓
Better scalability
```

However, the latter approach can introduce **eventual consistency** between the counting system and individual enforcement servers.

For example, there can be a period where the counting system has determined that a threshold has been exceeded but a particular server has not yet received the mitigation information.

Therefore, distributed rate limiting is ultimately a trade-off between:

- **Consistency of the limit**
- **Latency**
- **Availability**
- **Centralized coordination**
- **Scalability**

There is no single architecture that is optimal for every system.

For a normal backend application, a centralized Redis + Lua implementation may be more than sufficient and is considerably simpler to reason about.

At extremely large scale, however, architectures such as Cloudflare's demonstrate why it can become valuable to separate **counting** from **request enforcement** and move expensive coordination away from the critical path.

---

## Rate Limit Identity: What Should We Rate Limit By?

A rate limiter needs to decide **who or what the limit applies to**. The choice of identity is important because different types of identifiers have different trade-offs.

Common choices include:

### 1. IP Address

We can rate limit based on the client's IP address.

For example:

```text
rate_limit:{ip_address}
```

This is useful for unauthenticated endpoints where we do not yet know the identity of the user.

However, IP-based rate limiting has some important limitations.

Multiple legitimate users may share the same public IP address because of NAT, corporate networks, proxies, or mobile networks. In that situation, one user's traffic can consume the quota for other users.

IP addresses can also be rotated or changed, which makes them less reliable as a long-term identity for rate limiting.

Therefore, IP-based rate limiting is useful, particularly for public or pre-authentication endpoints, but it should not automatically be treated as a unique user identity.

---

### 2. User ID

For authenticated requests, we can rate limit based on the authenticated user's ID:

```text
rate_limit:{user_id}
```

This gives us a much cleaner mapping between a user and their rate-limit bucket.

However, it only works when the request has already been authenticated.

For example, a login endpoint cannot normally rate limit by user ID because the user may not have successfully authenticated yet.

Therefore, user ID is particularly useful for authenticated APIs but is not suitable as the only identity mechanism for pre-authentication endpoints.

---

### 3. API Key

For APIs where clients authenticate using API keys, we can rate limit directly against the API key:

```text
rate_limit:{api_key}
```

This is particularly suitable for B2B APIs because each client can have its own API key and therefore its own rate-limit bucket.

It also provides a clean way to isolate different clients from one another.

However, public-facing consumer applications may not expose API keys to their users, so this approach is not universally applicable.

---

### Choice for the Week 1 Implementation

For the Week 1 rate limiter, we will use **API key as the rate-limit identity**.

The rate limiter will maintain a separate Token Bucket for each API key:

```text
rate_limit:{api_key_A}
rate_limit:{api_key_B}
rate_limit:{api_key_C}
```

This gives us a simple and explicit identity model while allowing us to demonstrate per-client rate limiting without coupling the rate limiter to the application's authentication implementation.

This is an implementation choice for this project, rather than a claim that API keys are always the best choice.

In a real production system, the appropriate identity would depend on the endpoint and the application's authentication model. For example, an authenticated API might use a user ID, while a public pre-authentication endpoint might need to use an IP address or another form of client identity.

---

## Fail-Open vs Fail-Closed

A rate limiter often depends on external infrastructure such as Redis. This introduces an important question:

> **What should happen if the rate limiter itself becomes unavailable?**

There are two primary choices.

### Fail-Open

With **fail-open**, if the rate limiter encounters an unexpected error or Redis becomes unavailable, the request is allowed to continue without rate limiting.

```text
Request
   ↓
Rate limiter
   ↓
Redis unavailable
   ↓
ALLOW request
```

The advantage is that the rate limiter cannot become a cause of an API outage.

However, during the period in which the limiter is unavailable, clients may be able to send traffic without being rate limited.

This can be acceptable for APIs where availability is more important than temporarily losing abuse protection.

For example, a public content API might prefer serving legitimate users even if the rate limiter is temporarily unavailable.

---

### Fail-Closed

With **fail-closed**, if the rate limiter cannot determine whether a request should be allowed, the request is rejected.

```text
Request
   ↓
Rate limiter
   ↓
Redis unavailable
   ↓
REJECT request
```

This provides stronger protection when allowing uncontrolled traffic would be more dangerous than temporarily rejecting legitimate requests.

For example, a sensitive payments or security-critical API may prefer to fail closed if its rate-limiting or abuse-prevention mechanism is unavailable.

---

### The Trade-off

There is no universally correct answer.

The decision depends on the consequences of allowing traffic without rate limiting versus the consequences of temporarily rejecting legitimate traffic.

Conceptually:

```text
                    Redis unavailable
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
            Fail Open             Fail Closed
                │                     │
                ▼                     ▼
       Preserve availability    Preserve protection
                │                     │
                ▼                     ▼
       Risk of uncontrolled      Risk of rejecting
             traffic             legitimate traffic
```

Therefore, fail-open versus fail-closed should be treated as an **endpoint-specific reliability and security decision**, rather than a property that every rate limiter must follow.

For the Week 1 implementation, the rate limiter will be designed with **fail-open behavior** so that an outage or unexpected failure in the rate-limiting infrastructure does not take down the API itself.

---

## Testing Strategy

A rate limiter cannot be considered correct simply because it appears to work during a few manual requests.

The implementation needs to be tested for both its normal behavior and its behavior under concurrency.

The testing strategy will focus on four major areas:

1. Token refill behavior.
2. Rate-limit boundaries.
3. Concurrent requests.
4. Isolation between clients.

### 1. Token Refill Tests

We need to verify that tokens are refilled at the configured rate.

For example:

```text
Bucket capacity = 10 tokens
Refill rate     = 2 tokens/second
```

If the bucket initially contains zero tokens, after approximately one second it should contain approximately two tokens.

After another second, it should contain approximately four tokens.

We also need to verify that the number of tokens never exceeds the configured bucket capacity.

For example:

```text
Capacity = 10

Refill rate = 100 tokens/second

After a sufficient amount of time:
tokens == 10
```

It must never become 100, 1000, or any value greater than the bucket capacity.

The tests should also verify that elapsed time is used correctly when calculating the number of tokens that should be available.

---

### 2. Boundary Tests

We need to verify the exact point at which requests transition from allowed to rejected.

For example:

```text
Bucket capacity = 3
Initial tokens  = 3
```

We expect:

```text
Request 1 → ALLOW → 2 tokens
Request 2 → ALLOW → 1 token
Request 3 → ALLOW → 0 tokens
Request 4 → REJECT
```

We should then verify that after enough time has passed for a token to refill, another request can be accepted.

These tests verify that the implementation correctly handles both sides of the rate-limit boundary.

---

### 3. Concurrent Request Tests

This is one of the most important tests because race conditions can cause a rate limiter to incorrectly allow more requests than its configured limit.

For example, configure:

```text
Bucket capacity = 1
Available tokens = 1
```

Then send 100 requests concurrently.

The expected result is:

```text
1 request   → ALLOW
99 requests → REJECT
```

The exact request that succeeds does not matter, but the total number of successful requests must respect the available tokens.

This test should run against the **real Redis + Lua implementation**, rather than simply mocking Redis.

The purpose is to verify that the atomic operation in Redis actually protects the shared state when multiple requests arrive concurrently.

---

### 4. Client Isolation Tests

Each client should have its own independent rate-limit state.

For example:

```text
Client A:
Request 1 → ALLOW
Request 2 → ALLOW
Request 3 → REJECT

Client B:
Request 1 → ALLOW
```

Exhausting Client A's bucket must not affect Client B.

This verifies that the rate-limit key is correctly scoped to the API key:

```text
rate_limit:{api_key_A}
rate_limit:{api_key_B}
```

and that different clients do not accidentally share the same bucket.

---

### Testing Goal

The overall objective is to verify not only that the rate limiter produces the expected result under normal conditions, but also that its correctness holds under **concurrent access to shared state**.

The most important distinction is:

```text
"It works when I send requests manually."
                  ≠
"It is correct under concurrency."
```

The latter is the standard that the implementation should meet.
