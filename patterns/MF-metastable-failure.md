# MF — Metastable Failure Patterns

Metastable failure: the triggering condition resolves, but the system stays stuck in
a degraded state due to a sustaining feedback loop. Restart required, but the loop
makes restart harder.

---

## MF1 — Backpressure Queue Saturated by Deferred Flush Under Load

**Mechanism:** Under normal load, a bounded queue has space. Under a brief spike, the
queue fills faster than the flush worker can drain it. New items are rejected;
producers back off. But the queue STAYS near-full because the flush worker's
output rate is limited — a brief spike becomes a persistent saturation.

**Symptom:** Queue depth stuck near max; producers reporting rejection errors
long after the original spike is over.

**Fix rule:** The flush worker's throughput ceiling must exceed the steady-state
input rate by at least 2x. Add observable backpressure metrics:
```python
queue_depth_ratio = Gauge("queue_depth_ratio", "Queue depth as fraction of max")
```

---

## MF2 — Reconnect Storm: All Consumers Reconnect Simultaneously After Broker Restart

**Mechanism:** After a broker/server restart, all consumers have the same
reconnect-immediately logic. They all connect at the same moment, overwhelming the
broker's accept queue. Many fail, immediately retry, form a second storm.

**Fix rule:** Randomized exponential backoff:
```python
import random, asyncio

async def reconnect_with_jitter():
    for attempt in range(10):
        try:
            return await connect()
        except ConnectionRefusedError:
            wait = min(30, (2 ** attempt)) + random.uniform(0, 1)
            await asyncio.sleep(wait)
    raise RuntimeError("Reconnect failed after 10 attempts")
```

---

## MF3 — Cascading Log Volume Overwhelms Disk I/O

**Mechanism:** An error condition causes log output at WARNING or ERROR level on
every cycle. Log volume overwhelms disk I/O, slowing the process. The slow process
falls further behind, triggering more errors, more logging. Eventually: OOMKill or
disk full.

**Concrete instance (anonymized):**
```python
# BAD — logs on every loop iteration when component is unavailable
while True:
    if not component.is_ready():
        logger.warning("Component not ready, retrying...")   # every 100ms
    await asyncio.sleep(0.1)

# GOOD — log once on state change, not on every cycle
_was_ready = True
while True:
    ready = component.is_ready()
    if not ready and _was_ready:
        logger.warning("Component became unavailable")
    elif ready and not _was_ready:
        logger.info("Component recovered")
    _was_ready = ready
    await asyncio.sleep(0.1)
```
