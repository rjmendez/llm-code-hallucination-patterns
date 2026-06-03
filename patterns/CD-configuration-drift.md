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
