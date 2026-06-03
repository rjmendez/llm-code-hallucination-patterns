# SB — Serialization Boundary Patterns

Serialization boundary: data that is valid Python in memory fails at the moment it
crosses a wire (JSON, HTTP body, DB write, MQTT publish). Fails late, in production,
not at construction.

---

## SB1 — numpy ndarray Not JSON Serializable

**Mechanism:** `json.dumps(d)` raises `TypeError: Object of type ndarray is not JSON
serializable` when any dict value is a numpy array. Silent until that code path executes.

**Concrete instance (anonymized):**
```python
import numpy as np
import json

# LLM left embedding as numpy array in the dict:
record = {
    "item_id": "abc123",
    "label": "positive",
    "embedding": np.array([0.12, 0.34, 0.56, 0.78])   # problem
}

json.dumps(record)   # TypeError: Object of type ndarray is not JSON serializable
```

**Fix rule:** `.tolist()` at dict construction, not at `json.dumps()`:
```python
record = {
    "item_id": "abc123",
    "label": "positive",
    "embedding": embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
}
```
Also guard against `float('nan')` and `float('inf')` from sensor data.

---

## SB2 — Naive Datetime Mixed with Timezone-Aware Records in DB

**Mechanism:** `datetime.utcnow()` returns a naive datetime (no `tzinfo`). Mixed with
tz-aware ISO strings already in the DB, queries sort wrong and comparisons raise `TypeError`.

**Concrete instance (anonymized):**
```python
# LLM generated naive timestamp — works locally, breaks on comparison with stored tz-aware:
from datetime import datetime

event = {"id": "e1", "ts": datetime.utcnow().isoformat()}   # naive: "2026-06-03T14:22:00"

# Stored records have tz-aware timestamps: "2026-06-03T14:22:00+00:00"
# datetime comparison raises: TypeError: can't compare offset-naive and offset-aware datetimes
```

**Fix rule:**
```python
from datetime import datetime, timezone

event = {"id": "e1", "ts": datetime.now(tz=timezone.utc).isoformat()}
# Outputs: "2026-06-03T14:22:00+00:00" — consistently tz-aware
```
