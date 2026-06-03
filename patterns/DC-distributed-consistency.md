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
