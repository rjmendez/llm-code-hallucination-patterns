# DC — Distributed Consistency Patterns

Distributed consistency: stale reads, split singletons, lost writes in systems
spanning multiple processes, containers, or machines.

---

## DC1 — Stale Read: Write-Behind Cache Serves Old State to New Consumer

**Mechanism:** Component A writes to store S. Cache layer C is not invalidated.
Component B reads from cache C, gets pre-write value. Both A and B believe they have
the current state.

**Fix rule:** Write-through invalidation:
```python
def update_state(self, key: str, value):
    self.store.write(key, value)
    self.cache.delete(key)   # or .set(key, value, ttl=30)
```

---

## DC2 — Split Singleton: In-Memory Registry Diverges Across Worker Processes

**Mechanism:** A "singleton" dictionary or registry lives in process memory. With
multiple worker processes (Gunicorn, Celery, K8s pod replicas), each process has its
own copy. Registration in worker A is invisible to worker B.

**Symptom:** "Already registered" in one request, "Not found" in the next — both for
the same item.

**Fix rule:** Any registry that must be visible across processes must live in Redis,
a database, or a dedicated service. Never use process-global dicts for distributed state.

---

## DC3 — K8s ConfigMap Reload Lag Causes Two Live Config Versions

**Mechanism:** A ConfigMap update propagates to running pods on a K8s controller loop
(default ~2 minutes). During that window, some pods run with old config, others with new.

**Fix rule:** Use config versioning or checksums; detect divergence:
```bash
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.config-hash}{"\n"}{end}'
# All pods should have the same hash after a ConfigMap update
```
For critical config changes, use rolling restart to force fast reload:
```bash
kubectl rollout restart deployment/my-app
```

---

## DC4 — Lost Write Under High-Throughput MQTT Retain

**Mechanism:** MQTT retained messages are overwritten by the last publisher. Under
burst publishing from multiple producers, only the last message's state is preserved.
Earlier writes are permanently lost.

**Fix rule:** Retain is for "last known state" — never for audit trails or ledgers.
Use a persistent message bus (Kafka, Postgres NOTIFY) for writes that must not be lost.

---

## DC5 — Cross-Service Type Drift (Epoch Seconds vs Milliseconds, int vs string ID)

**Mechanism:** Service A encodes a timestamp as Unix epoch seconds (int). Service B
decodes it as milliseconds (int). Both sides use the same field name; no deserialization
error. The decoded value is silently wrong by a factor of 1000. LLMs generating each
service independently adopt the language-idiomatic convention without checking the
other side.

Common instances:
- **Epoch seconds vs milliseconds:** Python `time.time()` → seconds; JavaScript
  `Date.now()` → milliseconds. Same field, factor-of-1000 mismatch.
- **Integer ID vs string ID:** PostgreSQL `BIGINT` serialized as integer in Python,
  deserialized as string in JavaScript (JSON numbers > 2^53 lose precision).
- **Boolean encoding:** Python `True`/`False` in JSON vs `1`/`0` in query strings.

**Symptom:** Timestamps appear in the year 51000 (milliseconds parsed as seconds) or
1970 (seconds parsed as milliseconds). IDs compare unequal (`123 != "123"`). Boolean
conditions always/never fire.

**Concrete instance (anonymized):**
```python
# Python service (producer)
def serialize_event(event):
    return {
        "id": event.id,                          # int: 9007199254740993 (> JS safe int)
        "created_at": int(event.created_at.timestamp()),  # seconds since epoch
    }
```

```typescript
// TypeScript consumer (generated separately)
interface Event {
  id: string;         // string expected — Python sends int
  created_at: number; // assumed milliseconds — Python sends seconds
}
const ts = new Date(event.created_at);          // year 1970 (off by 1000x)
```

**Detection:**
```bash
# Find timestamp serialization across languages
grep -rn "time\.time()\|\.timestamp()\|Date\.now()" . \
  --include="*.py" --include="*.ts" --include="*.js"
# Find ID field types across service boundaries
grep -rn '"id":\|"user_id":\|\.id\b' . --include="*.py" --include="*.ts"
# Mismatch in unit or type across files is a DC5 candidate
```

**Fix rule:** Document the canonical unit for every shared timestamp field in an API
schema (OpenAPI, Protobuf). Prefer ISO 8601 strings over epoch integers — they are
unambiguous about precision. For IDs, use strings everywhere once values exceed 2^53.
