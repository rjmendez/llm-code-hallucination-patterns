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
