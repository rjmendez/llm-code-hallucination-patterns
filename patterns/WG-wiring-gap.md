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

---

## WG4 — Class Fully Implemented but Never Instantiated (Zero Call Sites)

**Mechanism:** An LLM generates a complete, self-contained class — constructor,
methods, event handlers, protocol logic — that is never referenced from any production
call site. The class compiles, has no syntax errors, and may even have unit tests
(testing it in isolation). But no component ever creates an instance, so the feature
it represents is permanently inactive.

This pattern typically occurs when an LLM implements a "next step" feature in a new
file without updating the wiring in the orchestrating class. The feature looks done;
it just never runs.

**Symptom:** A protocol that "should" be active (e.g., peer pairing, model sync,
federated learning) produces zero events, zero MQTT messages, and zero log lines —
despite apparently complete implementation.

**Concrete instance (anonymized):**
```kotlin
// PeerPairingController.kt — complete 300-line implementation:
class PeerPairingController(private val mqtt: MqttClient) {
    fun onPeerDiscovered(peerId: String) { /* ... full haptic + MQTT handshake ... */ }
    fun onPairingConfirmed(peerId: String) { /* ... model merge trigger ... */ }
}

// MainActivity.kt — LLM forgot to instantiate it:
class MainActivity : AppCompatActivity() {
    private lateinit var mqttClient: MqttClient
    // PeerPairingController is never created here.
    // No other file creates it either — zero call sites in the entire project.
}
```

**Detection:**
```bash
# Find class names with no constructor call sites:
CLASS="PeerPairingController"
grep -rn "class $CLASS\b" --include="*.kt" --include="*.java" .  # definition
grep -rn "\b$CLASS(" --include="*.kt" --include="*.java" .        # instantiation
# If only the definition line appears, it is never instantiated.

# Scripted sweep — find all class definitions then check for their constructors:
grep -rh "^class \|^data class \|^object " --include="*.kt" . \
  | sed 's/class \([A-Za-z]*\).*/\1/' \
  | while read cls; do
      count=$(grep -rn "\b${cls}(" --include="*.kt" --include="*.java" . | grep -v "class ${cls}(" | wc -l)
      echo "$count $cls"
    done | sort -n | head -20   # lowest counts first — zero means never instantiated
```

**Fix rule:**
1. For every new class that represents a live subsystem, immediately add its
   instantiation to the orchestrating class in the same commit — never in a follow-up.
2. Write an integration test that creates the class AND verifies at least one of its
   methods produces a side effect (MQTT publish, log entry, state change).

**Cross-references:** WG1 (no-op backend), OG1 (observability gap — no log entries because the class never runs)

---

---

## WG5 — Interactive UI Element with Empty Handler Body

**Mechanism:** An LLM generates a styled, labeled, interactive UI element (button,
clickable row, action item) whose tap handler is an empty lambda or a TODO stub.
The element looks interactive to the user — it may have hover/press states, an icon,
and a descriptive label — but tapping it does nothing.

**Symptom:** User taps a button. Nothing happens. No log entry. No navigation. No error.
The button does not visually respond (or responds briefly with a ripple) and then
returns to its original state. The feature the button represents is permanently dead.

**Concrete instance (anonymized):**
```kotlin
// Jetpack Compose — styled button with empty click handler:
Button(
    onClick = { /* RETRAIN stub: queued to queen */ },  // empty lambda
    modifier = Modifier.border(1.dp, MaterialTheme.colors.primary),
) {
    Text("RETRAIN → queen")
}

// Android XML + Java — button configured with no-op action:
quickActionButton.setText("SYNC");
quickActionButton.setOnClickListener(v -> {
    // TODO: wire to SyncManager
});
```

**Detection:**
```bash
# Compose — find clickable/onClick with empty or stub-only bodies:
grep -rn "onClick\s*=\s*{" --include="*.kt" . \
  | grep -E "onClick\s*=\s*\{\s*(//[^\n]*)?\s*\}"

# Android XML + Java — find setOnClickListener with only a comment body:
grep -A3 "setOnClickListener" --include="*.java" -rn . \
  | grep -B1 "// TODO\|// stub\|// placeholder"

# React/TypeScript equivalent:
grep -rn "onClick={() => {}}" --include="*.tsx" --include="*.ts" .
```

**Fix rule:**
1. Never merge a UI element whose click handler is an empty lambda or TODO.
   If the backend isn't ready, either hide the element (`visibility = GONE`) or
   disable it (`enabled = false`) with a logged reason.
2. Add a UI test that taps the element and asserts a side effect occurred
   (navigation event, state change, intent fired).

**Cross-references:** OG3 (observability gap — silent no-op with no log), CD3 (configuration makes the button appear enabled when it shouldn't)
