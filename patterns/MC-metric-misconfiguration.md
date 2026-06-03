# MC — Metric Misconfiguration Patterns

Metric misconfiguration: a metric is structurally correct (definition compiles, Prometheus
scrapes it) but semantically useless or misleading.

---

## MC1 — Metric Exported at Wrong Aggregation Level

**Mechanism:** A Gauge exports `current_queue_size` but is sampled once per batch,
not continuously. The scraper catches only the post-flush value (always near 0)
and never sees peak load.

**Concrete instance (anonymized):**
```python
# BAD — gauge is set at the start of flush, when queue is already near-empty
def flush_batch(self):
    self.queue_size_gauge.set(len(self.queue))   # reflects post-pull size, not peak
    for item in self.queue:
        self.process(item)
    self.queue.clear()

# GOOD — track peak between flushes
def enqueue(self, item):
    self.queue.append(item)
    self.queue_size_gauge.set(len(self.queue))   # updated on every enqueue
```

---

## MC1b — Counter Used Where Gauge Is Required

**Mechanism:** Prometheus Counters only go up. Using a Counter for a value that can
decrease (queue depth, active connections, worker utilization) produces a meaningless
monotonically-increasing series.

**Fix rule:**
- Counter: for totals that only accumulate (events processed, errors raised, bytes sent)
- Gauge: for values that go up AND down (queue depth, connection count, memory, temperature)
- Histogram: for distributions (latency, request size)

```python
# WRONG — queue depth as Counter
queue_depth = Counter("queue_depth", "Queue depth")   # can only inc(), never dec()

# RIGHT
queue_depth = Gauge("queue_depth", "Queue depth")     # can set() to any value
```
