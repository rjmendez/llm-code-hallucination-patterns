# AC — Async / Concurrency Patterns

---

## AC1 — `asyncio.get_event_loop()` Inside Async Context

**Mechanism:** Deprecated in Python 3.10+. Can return the wrong loop in executor threads.
Raises `DeprecationWarning` in 3.10, `RuntimeError: Event loop is closed` in test teardown.

**Concrete instance (anonymized):**
```python
# BAD
class Scheduler:
    def schedule(self, delay: float):
        deadline = asyncio.get_event_loop().time() + delay   # DeprecationWarning 3.10+

# GOOD
class Scheduler:
    async def schedule(self, delay: float):
        deadline = asyncio.get_running_loop().time() + delay
```

---

## AC2 — Missing Circuit Breaker Causes Cascading Failures

**Mechanism:** When component A depends on component B, and B becomes unavailable,
unbounded retries from A flood B's recovery path and extend the outage.

**Concrete instance (anonymized):**
```python
# BAD — no circuit breaker, hammers failing service
async def get_recommendation(item_id: str):
    while True:
        try:
            return await vector_db.query(item_id)
        except ConnectionError:
            await asyncio.sleep(0.1)   # retries every 100ms forever

# GOOD — exponential backoff + circuit breaker
async def get_recommendation(item_id: str):
    for attempt in range(5):
        try:
            return await vector_db.query(item_id)
        except ConnectionError:
            if attempt == 4:
                raise
            await asyncio.sleep(0.1 * (2 ** attempt) + random.uniform(0, 0.05))
```

---

## AC3 — No Graceful Shutdown Loses In-Flight Messages

**Mechanism:** A process that exits without draining its in-flight queue drops messages
silently. SIGTERM kills the process; in-flight items disappear with no log entry.

**Fix rule:**
```python
import signal, asyncio

shutdown_event = asyncio.Event()

def handle_sigterm(signum, frame):
    shutdown_event.set()

signal.signal(signal.SIGTERM, handle_sigterm)

async def main():
    # ... worker loop ...
    await shutdown_event.wait()
    # drain the queue with deadline
    await asyncio.wait_for(drain_queue(), timeout=30.0)
```

---

## AC4 — Async Task Exception Silently Discarded

**Mechanism:** `asyncio.create_task(coro)` fire-and-forget tasks whose exceptions
print to stderr and disappear. No caller sees them; no test catches them without an
explicit done callback.

**Concrete instance (anonymized):**
```python
# BAD — exception from flush_worker silently discarded
asyncio.create_task(self._flush_worker())

# GOOD — attach error handler
task = asyncio.create_task(self._flush_worker())
task.add_done_callback(
    lambda t: t.exception() and logger.error("flush_worker failed: %s", t.exception())
)

# BETTER (Python 3.11+) — TaskGroup propagates exceptions automatically
async with asyncio.TaskGroup() as tg:
    tg.create_task(self._flush_worker())
```
