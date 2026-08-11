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

---

## AC5 — Missing `await` on Coroutine Call (Silent No-Op)

**Mechanism:** An async function call is made without `await`. Python does not raise an
error — it creates a coroutine object and discards it. The operation silently does nothing.
LLMs frequently omit `await` when generating calls to functions that were recently
made async, or when generating callers independently from the callee.

**Symptom:** A function that should write to a DB, send a message, or flush a buffer
appears to succeed (no exception). The effect never happens. The coroutine warning
may appear in logs (`RuntimeWarning: coroutine was never awaited`) — but only if
warnings are not suppressed.

**Concrete instance (anonymized):**
```python
# BAD — flush is a coroutine; calling without await creates and discards it
class EventBuffer:
    async def flush(self):
        await self.queue.put_batch(self.pending)
        self.pending.clear()

    def on_shutdown(self):
        self.flush()   # ← coroutine object created and discarded, nothing flushed
```

```python
# GOOD
    async def on_shutdown(self):
        await self.flush()
```

**Detection:**
```bash
# Find async function definitions
grep -rn "async def " . --include="*.py" | awk -F'def ' '{print $2}' | awk '{print $1}' | sort -u
# For each async function name, find call sites that lack 'await':
grep -rn "self\.flush(\|self\.send(\|self\.commit(" . --include="*.py" | grep -v "await "
# Any call to a known-async method without leading 'await' is AC5
```

**Fix rule:** Any call to a coroutine must be awaited. Enable `RuntimeWarning` in tests:
```python
import warnings
warnings.filterwarnings("error", category=RuntimeWarning)
```
This converts the silent discard into a test failure.

---

## AC6 — Shared Mutable State Across Async Tasks Without Lock

**Mechanism:** Two async tasks share a mutable object (dict, list, counter, cache).
Since `asyncio` is cooperative, most in-Python mutations are not interrupted — but
code that does `await` between a read and a write creates a window for another task
to observe or modify the shared state. LLMs generating tasks independently often
omit the lock because each task looks safe in isolation.

**Symptom:** Race condition with non-deterministic outcomes: counter undercounts,
cache has stale values, list has duplicate entries. The bug only appears under
concurrent load; never in sequential unit tests.

**Concrete instance (anonymized):**
```python
# BAD — shared cache read-check-write across an await
class SessionCache:
    def __init__(self):
        self._cache: dict = {}

    async def get_or_create(self, key: str) -> Session:
        if key not in self._cache:          # Task A checks: key absent
            session = await db.create(key)  # Task A awaits — Task B runs, also creates
            self._cache[key] = session      # Task A stores; Task B also stored → two sessions
        return self._cache[key]
```

```python
# GOOD — asyncio.Lock protects the check-and-set
class SessionCache:
    def __init__(self):
        self._cache: dict = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, key: str) -> Session:
        async with self._lock:
            if key not in self._cache:
                self._cache[key] = await db.create(key)
            return self._cache[key]
```

**Detection:**
```bash
# Find class-level mutable fields (dict, list, set)
grep -rn "self\.\w\+ = {}\|self\.\w\+ = \[\]\|self\.\w\+ = set()" . --include="*.py"
# For each mutable field: do the methods that mutate it use asyncio.Lock?
grep -rn "asyncio\.Lock\|threading\.Lock\|async with.*lock" . --include="*.py"
# Classes with mutable fields but no lock are AC6 candidates
```

**Fix rule:** Any mutable field on a class shared across async tasks must be protected
by `asyncio.Lock`. The lock must wrap the entire read-check-write sequence, not just
the write.

---

## AC7 — Rust tokio::spawn JoinHandle Dropped: Task Cannot Be Aborted on Shutdown

**Mechanism:** `tokio::spawn(async { ... })` returns a `JoinHandle<T>`. If the
`JoinHandle` is immediately dropped (not stored, not awaited, not passed to a
`JoinSet`), the task runs until completion with no way to cancel it externally.
When a shutdown signal arrives, the task continues indefinitely — holding open
network connections, DB handles, or MQTT sessions — because there is no abort
path.

LLMs commonly write `tokio::spawn(handler(conn, mqtt.clone()));` as a
"fire and forget" pattern that looks correct for short tasks but becomes a
resource leak for long-running connection handlers.

**Symptom:** On SIGTERM or graceful restart, old connection handlers continue
processing and holding resources. Log shows "shutting down" but TCP connections
and MQTT sessions stay open. Memory and FD counts don't drop until timeout.

**Concrete instance (anonymized):**
```rust
// BAD — JoinHandle dropped immediately; no abort path
async fn accept_loop(listener: TcpListener, mqtt: MqttClient) {
    loop {
        let (conn, _addr) = listener.accept().await.unwrap();
        let mqtt = mqtt.clone();
        tokio::spawn(async move {
            handle_connection(conn, mqtt).await;  // runs forever; cannot be stopped
        });
        // JoinHandle dropped here — task is now untracked
    }
}

// GOOD — JoinSet tracks all handles; abort_all() on shutdown
async fn accept_loop(
    listener: TcpListener,
    mqtt: MqttClient,
    cancel: CancellationToken,
) {
    let mut set = tokio::task::JoinSet::new();
    loop {
        tokio::select! {
            result = listener.accept() => {
                let (conn, _) = result.unwrap();
                let mqtt = mqtt.clone();
                let cancel = cancel.clone();
                set.spawn(async move {
                    tokio::select! {
                        _ = handle_connection(conn, mqtt) => {}
                        _ = cancel.cancelled() => {}
                    }
                });
            }
            _ = cancel.cancelled() => {
                set.abort_all();
                break;
            }
        }
    }
}
```

**Detection:**
```bash
# Find tokio::spawn calls whose return value is not bound:
grep -rn "tokio::spawn(" --include="*.rs" . | grep -v "let \|= tokio::spawn\|\.spawn("

# More precise: find spawn() not preceded by let/=:
grep -Prn "(?<!let \w{1,40})(?<!=\s)tokio::spawn\(" --include="*.rs" .
```

**Fix rule:**
1. Always bind `tokio::spawn` return values: `let handle = tokio::spawn(...)`.
2. For connection-per-task patterns, use `JoinSet::spawn` so `abort_all()` can be
   called from the shutdown path.
3. Pass a `CancellationToken` into every long-running spawned task and select on it.
4. In tests, assert that spawned tasks complete (or are aborted) within a deadline
   after the shutdown signal is sent.

**Cross-references:** AC3 (no graceful shutdown loses in-flight messages), AC4 (exception silently discarded from dropped JoinHandle)
