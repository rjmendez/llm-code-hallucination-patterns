# WG — Wiring Gap Patterns

Wiring gap: a component is named for an integration it never actually performs.
The system "looks wired" but the integration is silent no-op.

---

## WG1 — Component Named for Integration but Calling No-Op Backend

**Mechanism:** A class is named `MetricsPublisher`, `AlertNotifier`, or
`TelemetryExporter`. Its constructor succeeds. Its `.publish()` method exists
and returns without error. But the actual outbound call was never wired — the
method is a stub or logs a local-only debug line.

**Concrete instance (anonymized):**
```python
class AlertNotifier:
    def __init__(self, config):
        self.webhook_url = config.get("webhook_url")    # may be None

    def send(self, message: str):
        if self.webhook_url:
            # LLM generated the import but not the actual HTTP call:
            logger.debug("Would send alert: %s", message)   # no requests.post!
        # If webhook_url is None: also silently returns
```

**Symptom:** Alerts "sent" in logs; no alerts received in the target system.
Integration tests pass because the mock never checks for an outbound HTTP call.

**Detection:**
```bash
# Find classes with "Publisher", "Notifier", "Exporter", "Sender" in name
# that have no HTTP/socket calls in their send/publish methods:
grep -rn "class.*Publisher\|class.*Notifier\|class.*Exporter\|class.*Sender" --include="*.py" .
# For each class, check for requests.post, httpx.post, socket.send, etc.
```

**Fix rule:**
1. Add an integration test that patches `requests.post` and asserts it was called with the expected URL.
2. If no HTTP call exists in the method body, add it.
3. If `webhook_url` is None, raise `ConfigurationError` on init — never silently no-op.

---

## WG2 — Silent Observer (Handler Registered, Body Is a No-Op)

**Mechanism:** An event handler is registered (`addEventListener`, `@receiver`,
`add_listener`, `.subscribe()`). The handler fires — but its body only logs the event
or returns immediately for certain event types. The event is "handled": no
unhandled-event error, no obvious symptom. State is not updated; downstream actions
do not trigger.

**Symptom:** Events arrive (visible in logs: "received event X"). Nothing else happens.
Downstream state remains unchanged. The system appears to be listening but isn't acting.

**Concrete instance (anonymized):**
```python
# BAD — error handler registered, body only logs
def on_connection_error(event):
    logger.warning("Connection error: %s", event)
    # missing: trigger reconnect, increment error counter, alert on-call

event_bus.subscribe("connection.error", on_connection_error)
```

```python
# GOOD — handler performs the intended action
def on_connection_error(event):
    logger.warning("Connection error: %s", event)
    error_counter.inc()
    schedule_reconnect(event.endpoint, delay=BACKOFF_SECONDS)
    if error_counter.value > ALERT_THRESHOLD:
        alerting.notify("connection_error", event)
```

**Detection:**
```bash
# Find event handler registrations
grep -rn "addEventListener\|add_listener\|\.subscribe(\|@receiver\|register_handler" . --include="*.py" --include="*.ts"
# For each: read the handler body — does it do anything besides log?
# Handlers that only call logger.* / console.log are WG2 candidates
```

**Fix rule:** For every registered handler, identify the state mutation or downstream
action the event should trigger. If the handler only logs, it is a stub. Add a unit
test that asserts the intended side effect (state change, counter increment, downstream
call) when the handler fires.

---

## WG3 — Fake Health Check (Always Returns 200)

**Mechanism:** A `/health`, `/ready`, or `/live` endpoint returns `{"status": "ok"}`
unconditionally. It does not probe the database, message queue, ML model, or external
dependencies it is supposed to check. Kubernetes, load balancers, and monitoring
systems mark the instance healthy when it is broken.

**Symptom:** A pod loses its DB connection. The health endpoint still returns 200.
K8s continues routing traffic to the broken pod. Errors are reported by clients, not
by infrastructure.

**Concrete instance (anonymized):**
```python
# BAD — health check does not probe dependencies
@app.get("/health")
def health():
    return {"status": "ok"}   # always 200 regardless of DB/queue state
```

```python
# GOOD — health check probes dependencies
@app.get("/health")
def health():
    checks = {}
    try:
        db.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"

    try:
        queue_client.ping()
        checks["queue"] = "ok"
    except Exception as exc:
        checks["queue"] = f"error: {exc}"

    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": checks}, status_code=200 if ok else 503)
```

**Detection:**
```bash
# Find health/readiness endpoints
grep -rn '"/health"\|"/ready"\|"/live"\|health_check' . --include="*.py" --include="*.ts" --include="*.go"
# For each handler: does the body contain a real probe (db query, ping, model inference)?
# Handlers that return a hardcoded dict without any try/except probe are WG3 candidates
```

**Fix rule:** Every health endpoint must perform at least one real probe of each critical
dependency. If any probe fails, return HTTP 503. Never catch all exceptions and
return 200 — that defeats the purpose of the health check.
