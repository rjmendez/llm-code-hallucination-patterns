# OG — Observability Gap Patterns

Observability gap: a bug exists but the evidence was architecturally never recorded.
No log entry, no metric, no trace. Root cause must be reconstructed by inference.

---

## OG1 — Exception Swallowed Without Logging

**Mechanism:** `except Exception: pass` or `except Exception: return None` hides
failures. The function returns None; the caller treats it as "nothing found";
no trace of the original error anywhere.

**Concrete instance (anonymized):**
```python
# BAD
def get_item(self, item_id: str):
    try:
        return self.db.query(item_id)
    except Exception:
        return None   # error vanishes

# GOOD — log and re-raise or log and return sentinel with context
def get_item(self, item_id: str):
    try:
        return self.db.query(item_id)
    except Exception as e:
        logger.error("get_item(%s) failed: %s", item_id, e, exc_info=True)
        return None  # or raise, depending on caller contract
```

---

## OG2 — Metric Initialized But Never Incremented in the Hot Path

**Mechanism:** A metric counter is defined and appears in Prometheus. It shows `0`.
An engineer reads `0` as "no errors" — but the counter was never wired to the actual
error path. `0` means "not measured," not "no errors."

**Fix rule:** After adding any metric, verify it fires under test:
```python
def test_metric_fires():
    pipeline.process(bad_input)
    assert metrics.errors_total._value.get() > 0  # verify it actually increments
```

---

## OG3 — No Correlation ID Across Service Boundaries

**Mechanism:** Service A generates an error. Service B receives a downstream failure.
The logs from A and B have no shared ID, so there is no way to correlate which A
request caused which B failure.

**Fix rule:** Propagate a correlation/trace ID in every outbound request:
```python
import uuid

TRACE_ID_HEADER = "X-Trace-Id"

async def call_downstream(session, url, payload, trace_id=None):
    trace_id = trace_id or str(uuid.uuid4())
    headers = {TRACE_ID_HEADER: trace_id}
    async with session.post(url, json=payload, headers=headers) as resp:
        logger.info("downstream call trace=%s status=%d", trace_id, resp.status)
        return await resp.json()
```

---

## OG4 — Prometheus Scrape Interval Longer Than Event Duration

**Mechanism:** A Prometheus counter is incremented during a brief error burst. If the
scrape interval (default 15s) is longer than the burst duration, the counter is never
sampled during the burst. It looks like no errors happened.

**Fix rule:** For sub-15s events, use a `Summary` or `Histogram` instead of bare
counters. For critical counters, reduce scrape interval:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: critical_service
    scrape_interval: 5s
```
