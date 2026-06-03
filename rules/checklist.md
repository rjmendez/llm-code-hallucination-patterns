# LLM Code Review Checklist

Use this before committing any LLM-generated code or when debugging unexpected failures.
Jump to the category matching your symptom.

---

## Symptom → Category Lookup

| Symptom | Check |
|---------|-------|
| AttributeError on `._*` private attr | H1 |
| ValueError: Duplicated timeseries | H2 |
| NameError: undefined name | H3 |
| AttributeError: 'NoneType' on method chain | H4 |
| Test assertion hardcoded wrong value | H5 |
| DeprecationWarning on datetime/asyncio | H6 |
| Test always passes regardless of input | H7 or SS1 |
| TypeError on collection type | H8 |
| RuntimeWarning: coroutine never awaited | H9 |
| Test assertion shifts after column add | SD1 |
| OperationalError: no such column | SD2 |
| TypeError on `.inc()` / `.set()` | SD3 |
| YAML load returns wrong doc count | SD4 |
| Boolean method always returns same value | SS1 |
| Queue never fills in tests | SS2 |
| Expected exception not raised | SS3 |
| Metric shows wrong value | SS4 or MC1 |
| Batch returns partial results silently | SS5 |
| Two tests for same fn contradict | SS6 |
| Compiler reports one error at a time | CP1 |
| Single patch causes N test failures | CP2 |
| UnboundLocalError | SL1 |
| Mock active in fixture, dead in test body | SL2 |
| TypeError: ndarray not JSON serializable | SB1 |
| TypeError: naive vs aware datetime | SB2 |
| DeprecationWarning: get_event_loop | AC1 |
| System degrades under any load | AC2 |
| Messages lost on SIGTERM | AC3 |
| Background task exception invisible | AC4 |
| Metric values from previous test leak | TEC1 |
| Stash-based baseline count off | TEC2 |
| File regressed to earlier state | AT1 |
| Changes lost after parallel agent run | AT2 |
| Wrong module version in execute_code | AT3 |
| Agent reported "done", artifact broken | AT4 |
| Agent explanation doesn't match error | AT5 |
| Agent repeats completed work | AT6 |
| ValueError before validating | PB1 |
| Pydantic field silently defaults | PB2 |
| None propagated across network | PB3 |
| Config string parsed as float | PB4 |
| System stays degraded after trigger resolves | MF1–MF3 |
| Same key returns different state per pod | DC1–DC4 |
| Different behavior in staging vs prod | CD1–CD3 |
| Bug exists, no log entry | OG1–OG4 |
| Integration "working", target never receives | WG1 |
| Metric stuck at 0 or only goes up | MC1, MC1b |

---

## Pre-Commit Checklist

### For any LLM-generated code:

- [ ] **H3** Import check: every name used at the call site is in the import block
  ```bash
  head -30 changed_file.py | grep import
  ```

- [ ] **H6** Deprecated API check:
  ```bash
  python3 -W error -c "import your_module" 2>&1 | grep DeprecationWarning
  ```

- [ ] **H7** Vacuous test check:
  ```bash
  grep -rn "^\s*[a-z_].*==[^=]" --include="test_*.py" . | grep -v "assert\|#"
  ```

- [ ] **H2** Metric name collision check (before adding any new metric):
  ```bash
  grep -rn "Counter\|Gauge\|Histogram" --include="*.py" . | grep '"your_metric_name"'
  ```

### For any wiring patch (CP2 — Interface Impact Scan):

- [ ] List all changed symbols:
  ```bash
  git diff --cached | grep "^+.*\(def \|class \|    [a-z_]*:\)"
  ```

- [ ] Find all test references to each changed symbol:
  ```bash
  grep -rn "ChangedClassName\|changed_method" --include="test_*.py" .
  ```

- [ ] Check for positional index break (SD1):
  ```bash
  grep -rn "\brow\[.\]\|\bvalues\[.\]" --include="test_*.py" .
  ```

- [ ] Check for label/shape break (SD3):
  ```bash
  grep -rn "\.inc()\|\.set(" --include="*.py" . | head -20
  ```

- [ ] Check for dedup/filter that could swallow test stimuli (SS2):
  ```bash
  grep -rn "dedup\|deduplicate\|seen\|already_processed" --include="*.py" .
  ```

- [ ] Check for fixtures using `return` inside `with mock.patch` (SL2):
  ```bash
  grep -A20 "@pytest.fixture" --include="test_*.py" -rn . \
    | grep -B5 "return " | grep "with mock\|with patch"
  ```

### For any pytest fixture:

- [ ] **SL2** All fixtures that use context managers must use `yield`, not `return`

- [ ] **TEC1** Metrics reset in fixture if any metric counter used across tests:
  ```bash
  grep -rn "Counter\|Gauge\|Histogram" --include="test_*.py" .
  # If any test checks metric values: add autouse fixture that resets registry
  ```

---

## Quick Verification Commands

```bash
# Full pre-commit check suite
python3 -W error -m pytest --tb=short -q 2>&1 | tail -20
ruff check . --select=F821,B015,LH001,LH003,LH007,LH009

# Baseline before touching anything
python3 -m pytest --tb=no -q 2>&1 | tail -3

# Import safety
python3 -c "from your_module import YourClass; print('OK')"

# Schema verification
sqlite3 your.db "PRAGMA table_info(your_table);" 2>/dev/null | column -t
python3 -c "import yaml; docs=list(yaml.safe_load_all(open('manifests.yaml'))); print(len(docs), 'docs')"
```
