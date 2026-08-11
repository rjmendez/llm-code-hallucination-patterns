# CD — Configuration Drift Patterns

Configuration drift: code is correct; config is wrong for the deployment environment.
No exception at startup — silent mismatch between what the code expects and what's deployed.

---

## CD1 — Environment Variable Staging/Production Mismatch

**Mechanism:** A service reads `DB_HOST` from env. Dev/staging uses a local host;
production uses a different hostname. The code is identical; behavior diverges entirely
based on the env. Common: staging passes all tests but production silently fails.

**Detection:**
```bash
# Dump all env vars as a snapshot for comparison:
kubectl exec deploy/my-app -- env | sort > env-snapshot-$(date +%Y%m%d).txt

# Diff two environments:
diff env-snapshot-staging-*.txt env-snapshot-prod-*.txt
```

---

## CD2 — Log Level Too Verbose in Production Causes I/O Bottleneck

**Mechanism:** `LOG_LEVEL=DEBUG` accidentally set in production. Debug-level log
statements in hot paths produce megabytes per second. Disk I/O becomes the bottleneck.
Service appears slow; no obvious error.

**Fix rule:** Validate log level at startup:
```python
import os, logging, sys

level = os.getenv("LOG_LEVEL", "INFO").upper()
if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    print(f"Invalid LOG_LEVEL={level}, defaulting to INFO", file=sys.stderr)
    level = "INFO"
logging.basicConfig(level=getattr(logging, level))
```

---

## CD3 — Resource Limit Too Low: OOMKill Looks Like Crash

**Mechanism:** A container's `resources.limits.memory` is set lower than the service's
actual working-set peak. Kubernetes OOMKills the pod; the exit code looks identical to
an application crash. Post-mortem focuses on the wrong thing.

**Detection:**
```bash
kubectl describe pod <pod> | grep -A10 "OOMKilled\|Exit Code"
kubectl top pod <pod>  # real memory usage
```

**Fix rule:** Set limits based on observed peak + 30% headroom, not guesses.
Add a `resources.limits.memory` alert:
```yaml
- alert: ContainerNearOOM
  expr: container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.85
  for: 5m
```

---

## CD4 — Environment Variable Used in Code But Not Declared in Deployment Manifests

**Mechanism:** A developer adds `os.environ["NEW_API_KEY"]` to application code. The
env var is set in their local `.env` file. It is not added to the Dockerfile `ENV`,
Kubernetes `ConfigMap`/`Secret`, or CI pipeline environment. Deployment succeeds;
the application crashes on startup or silently uses `None` in production.

**Symptom:** `KeyError: 'NEW_API_KEY'` in production logs. Or, if the code uses
`os.environ.get("NEW_API_KEY")` with no default, it silently operates with `None`
and fails on the first call that uses the value.

**Concrete instance (anonymized):**
```python
# BAD — env var used but not declared in any manifest
import os
API_KEY = os.environ["EXTERNAL_SERVICE_KEY"]   # raises KeyError in prod if unset

# Also bad — silent None
API_KEY = os.environ.get("EXTERNAL_SERVICE_KEY")  # None in prod; fails on first use
```

```python
# GOOD — fail fast with a clear message if unset
import os

def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value

API_KEY = _require_env("EXTERNAL_SERVICE_KEY")
```

**Detection:**
```bash
# Find all env var accesses in application code
grep -rn 'os\.environ\["[^"]\+"\]\|os\.environ\.get("[^"]\+")\|process\.env\.' \
  . --include="*.py" --include="*.ts" --include="*.js" | grep -v test

# Find all declared env vars in deployment manifests
grep -rn "name:\|value:\|secretKeyRef:\|configMapKeyRef:" \
  . --include="*.yaml" --include="*.yml" --include="Dockerfile" --include=".env.example"

# Diff: env vars in code vs vars in manifests — any in code but not manifests is CD4
```

**Fix rule:** For every `os.environ["VAR"]` added to code, add the corresponding entry
to `.env.example`, the Dockerfile `ENV` section, and the k8s `ConfigMap` or `Secret`.
Add a startup validation function that calls `_require_env()` for all required vars
before the application begins serving requests.

---

## CD5 — Production-Unsafe Default Value

**Mechanism:** A configuration value has a default that is safe for development but
dangerous in production: `DEBUG=True`, `SECRET_KEY="dev-key"`, `CORS_ALLOW_ALL=True`,
`SSL_VERIFY=False`. LLMs generate the default as convenient for local use; the
production deployment inherits it silently.

**Symptom:** Debug pages expose stack traces in production. CORS allows any origin
(security boundary broken). TLS verification is disabled (MITM risk). Secret keys
are guessable (session forgery risk).

**Concrete instance (anonymized):**
```python
# BAD — unsafe defaults that will ship to production
DEBUG = os.environ.get("DEBUG", "true").lower() == "true"   # ← default: DEBUG on
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")  # guessable
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ORIGINS", "*")   # wildcard
SSL_VERIFY = os.environ.get("SSL_VERIFY", "false") == "true"  # ← default: off
```

```python
# GOOD — defaults that are safe in production; dev must explicitly opt in
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
SECRET_KEY = _require_env("SECRET_KEY")               # no default; must be set
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ORIGINS", "").split(",")  # empty = none
SSL_VERIFY = os.environ.get("SSL_VERIFY", "true") == "true"  # ← default: on
```

**Detection:**
```bash
# Find configuration defaults that are security-sensitive
grep -rn 'get("DEBUG",\|get("SECRET_KEY",\|get("CORS_',\|get("SSL_VERIFY",' \
  . --include="*.py" --include="*.ts" --include="*.env*"
# Check each default value — is it the safe value or the convenient-for-dev value?
```

**Fix rule:** The safe production value must be the default. Development must
explicitly override to the unsafe value. Never ship a default of `DEBUG=True`,
`SECRET_KEY=<literal>`, `CORS_ORIGINS=*`, or `SSL_VERIFY=False`.

---

## CD6 — Hardcoded Endpoint in Production Code Path

**Mechanism:** A developer hardcodes `http://localhost:8080`, `http://127.0.0.1:5432`,
or a specific IP address in a production code path. The service works locally and in
a single-node test environment. In a multi-container or multi-host deployment, the
hardcoded address is unreachable.

**Symptom:** `ConnectionRefusedError: [Errno 111] Connection refused` in production.
Or the service connects to a completely different host that happens to be running the
same port (a different service's port), causing silent data corruption.

**Concrete instance (anonymized):**
```python
# BAD — hardcoded local address in production code path
DB_URL = "postgresql://user:password@localhost:5432/appdb"
REDIS_URL = "redis://127.0.0.1:6379"
```

```python
# GOOD — all addresses from environment
DB_URL = _require_env("DATABASE_URL")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")  # container name
```

**Detection:**
```bash
# Find hardcoded localhost/127.0.0.1 references in non-test files
grep -rn "localhost\|127\.0\.0\.1\|0\.0\.0\.0" . \
  --include="*.py" --include="*.ts" --include="*.go" --include="*.java" \
  | grep -v "test\|spec\|__pycache__\|\.git"
# Any hardcoded address in a production code path (not test) is CD6
```

**Fix rule:** All service addresses, ports, and URLs must come from environment
variables or a config file that is not committed. The only acceptable hardcoded
addresses in non-test code are service discovery names (container names in
docker-compose, Kubernetes service names) — never IP addresses.

---

## CD7 — Debug/Diagnostic Endpoint Compiled into Release Build (Missing Build-Type Gate)

**Mechanism:** An LLM generates a diagnostic probe, metrics server, or device-enumeration
command for debugging purposes but omits the build-type guard (`BuildConfig.DEBUG`,
`#[cfg(debug_assertions)]`, `if __debug__:`, etc.) that prevents it from being active
in production/release builds. The code ships to real users with full diagnostic
capability exposed.

**Symptom:** A production app exposes an HTTP endpoint, an MQTT command handler, or a
background scanning loop that returns detailed internal state (hardware MACs, counters,
service trees, memory layout) to any caller who knows the endpoint or topic name.

**Concrete instance (anonymized):**
```java
// BAD — diagnostic BLE probe reachable from release APK via MQTT command:
case "device_probe": {
    JSONObject r = BleProbe.run(context);   // returns MAC, bonded devices, GATT services
    mqtt.publishAck(r);
    break;
}

// GOOD — gate behind debug build type:
case "device_probe": {
    if (!BuildConfig.DEBUG) break;          // no-op in release; full probe in debug
    JSONObject r = BleProbe.run(context);
    mqtt.publishAck(r);
    break;
}
```

```rust
// Rust equivalent — gate behind cfg(debug_assertions):
#[cfg(debug_assertions)]
fn handle_probe_command(ctx: &Context) -> anyhow::Result<Value> {
    collect_diagnostic_info(ctx)
}
// Without cfg gate, handle_probe_command is reachable in release.
```

**Detection:**
```bash
# Android — find command dispatch cases calling probe/diagnostic classes
# without a surrounding BuildConfig.DEBUG check:
grep -n "case \".*probe\"\|case \".*diag\"\|case \".*debug\"" \
  app/src/main/java/**/*.java | while IFS=: read file linenum rest; do
    context=$(sed -n "$((linenum-2)),$((linenum+4))p" "$file")
    echo "$context" | grep -q "BuildConfig.DEBUG" \
      || echo "UNGUARDED: $file:$linenum"
done

# Find HTTP/socket servers started unconditionally (not inside an if-DEBUG block):
grep -rn "new ServerSocket\|HttpServer\|startServer" --include="*.java" . \
  | grep -v "BuildConfig.DEBUG\|if.*debug"
```

**Fix rule:**
1. Any command handler, HTTP/socket endpoint, or background scanner that exposes device
   internals MUST have a build-type check at the dispatch site.
2. Prefer removing diagnostic classes from release builds via Proguard/R8 rules or
   `sourceSets` rather than runtime guards — a missing class cannot be called.
3. Code review rule: grep for diagnostic class names (`Probe`, `Diag`, `Scanner`, `Dump`)
   in the command dispatch table and verify each has an explicit build-type gate.

**Cross-references:** OG4 (exposure visible in network traces but not app logs), CD1 (env mismatch between debug and release)

---
