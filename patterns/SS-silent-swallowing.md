# SS — Silent Swallowing Patterns

Silent swallowing: code accepts bad input, wrong type, or duplicate stimulus and returns
a plausible-looking result (empty list, conservative default, True/False) without any
error. Tests pass at the wrong level; production silently misbehaves.

---

## SS1 — Wrong Type Accepted, Conservative Default Fires

**Mechanism:** When a function signature is `def f(self, required_list, optional_score=None)`
and a caller passes a dict as `required_list`, Python accepts it without TypeError.
If the function has `if optional_score is None: return True`, it silently returns
the wrong value every call.

**Symptom:** A boolean method that always returns the same value regardless of inputs.

**Concrete instance (anonymized):**
```python
def should_escalate(self, state_history: list[dict], risk_score: float) -> bool:
    if risk_score is None:
        return True   # conservative default
    return any(s["level"] > 0.8 for s in state_history) and risk_score > 0.7

# LLM-generated test passes wrong type:
result = obj.should_escalate(snapshot_dict)   # passes dict as state_history
# risk_score defaults to None → always returns True → test always passes → bug hidden
```

**Fix rule:**
```python
import inspect
print(inspect.signature(obj.should_escalate))
# Compare every test call site to the production call site type-by-type
```

---

## SS2 — Dedup / Rate-Limit Gate Absorbs Repeated Test Stimuli

**Mechanism:** When a dedup or throttle filter is added to a pipeline, tests that submit
identical payloads to fill a queue silently stop filling it.

**Concrete instance (anonymized):**
```python
# Test tries to fill queue with 10 events to trigger backpressure:
for i in range(10):
    pipeline.submit({"type": "alert", "source": "sensor_1"})   # all identical
assert pipeline.queue_depth() == 10  # FAILS: dedup filtered 9 of them → depth is 1

# Fix: vary the payload to bypass the dedup gate
for i in range(10):
    pipeline.submit({"type": "alert", "source": "sensor_1", "seq": i})  # unique
# Add comment: # seq varies to bypass dedup gate
```

**Detection:**
```bash
grep -rn "for i in range\|identical\|repeat" --include="test_*.py" .
```

---

## SS3 — Input Validation After Early-Return Guard

**Mechanism:** A `raise ValueError` placed AFTER `if not self.config: return []` is
never reached when the guard fires first. Tests that probe validation receive `[]`
instead of the expected exception.

**Concrete instance (anonymized):**
```python
def query_records(self, filters: dict) -> list:
    if not self.connection_string:
        return []   # guard fires first
    if not filters:
        raise ValueError("filters cannot be empty")   # never reached when conn missing
```

**Fix rule:** Input validation ALWAYS precedes resource-acquisition guards:
```python
def query_records(self, filters: dict) -> list:
    if not filters:
        raise ValueError("filters cannot be empty")   # validate first
    if not self.connection_string:
        return []
```

---

## SS4 — Metric Value Reset on Irrelevant Control-Flow Branch

**Mechanism:** A running metric is reset to zero inside an else-branch that represents
"nothing notable happened this cycle" — not "the metric should be zero." Every
non-event wipes accumulated signal.

**Concrete instance (anonymized):**
```python
# BAD — zeros metric on every non-event cycle
if event_count >= threshold:
    agreement_gauge.set(compute_agreement(events))   # correct
else:
    agreement_gauge.set(0.0)   # WRONG: means "no data" but zeroes the gauge

# A system with 90% agreement shows 0.0 whenever no-quorum fires
```

**Fix rule:**
```python
# Only update when there is new data
if event_count >= threshold:
    agreement_gauge.set(compute_agreement(events))
# else: no new data — leave gauge unchanged
```

---

## SS5 — Per-Record try/except Breaks Batch Transaction Atomicity

**Mechanism:** A batch-insert loop wraps each DB write in its own `try/except`. On
failure, the exception is caught and the loop continues. The batch function returns
all N IDs and "commits" whatever succeeded. Caller believes the batch was atomic; it wasn't.

**Concrete instance (anonymized):**
```python
# BAD — partial writes silently succeed
def batch_insert(self, records: list) -> list[str]:
    ids = []
    for rec in records:
        try:
            cursor.execute(INSERT_SQL, rec.to_tuple())
            ids.append(rec.id)
        except Exception:
            pass   # swallowed: partial batch looks like success
    conn.commit()
    return ids   # returns all IDs even if some inserts failed

# GOOD — atomic batch
def batch_insert(self, records: list) -> list[str]:
    try:
        for rec in records:
            cursor.execute(INSERT_SQL, rec.to_tuple())
        conn.commit()
        return [r.id for r in records]
    except Exception:
        conn.rollback()
        return []
```

---

## SS6 — Conflicting Test Assertions: Two Tests for Same Contract, Different Versions

**Mechanism:** Two separate test files test the same function but were written at
different points in its evolution. One reflects an intermediate fix; the other reflects
the final contract. One MUST be wrong, but both pass in isolation.

**Concrete instance (anonymized):**
```python
# test_initial_fix.py — written during intermediate "sequential int" fix:
assert record_ids == [0, 1, 2, 3, 4]

# test_final_contract.py — written for "UUID as record ID" final design:
assert record.id == expected_uuid

# After the final fix: running both → one fails
# The "old" test is a time-capsule of a contract that no longer exists
```

**Fix rule:** When fixing a bug that changes a fundamental contract (ID type, return
type, error vs empty), search ALL test files for assertions about that function and
reconcile them in the same commit.
```bash
grep -rn "record_ids\|record\.id\|function_under_test" test_*.py
```
