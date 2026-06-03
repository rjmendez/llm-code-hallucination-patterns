# SD — Schema Drift Patterns

Schema drift: a structural contract (DB column, YAML key, tuple position, metric label,
object type) changes in one place but assumptions about its OLD shape remain elsewhere.
Never raises at the change site — always explodes downstream.

---

## SD1 — SQL Column Insertion Shifts Positional Tuple Assertions

**Mechanism:** Adding a column to an `INSERT` statement shifts every downstream
`VALUES[N]` assertion by +1. No `IndexError` fires — the wrong column is silently checked.

**Concrete instance (anonymized):**
```python
# Original INSERT (5 columns):
cursor.execute("""
    INSERT INTO events (source, category, severity, payload, ts)
    VALUES (?, ?, ?, ?, ?)
""", (rec.source, rec.category, rec.severity, rec.payload, rec.ts))

# LLM adds 'region' at position 3:
cursor.execute("""
    INSERT INTO events (source, category, region, severity, payload, ts)
    VALUES (?, ?, ?, ?, ?, ?)
""", (rec.source, rec.category, rec.region, rec.severity, rec.payload, rec.ts))

# Test that was checking severity:
row = cursor.execute("SELECT * FROM events LIMIT 1").fetchone()
assert row[2] == "high"    # WAS severity; NOW silently tests region
```

**Detection:**
```bash
# Find positional integer index access on query results
grep -rn "\brow\[.\]\|\bvalues\[.\]\|\bresult\[.\]" --include="test_*.py" .
```

**Fix rule:** When adding any SQL column, immediately grep all test assertions for
numeric index access on that INSERT's VALUES tuple and increment them. Better: use
`sqlite3.Row` or named tuple access instead of positional integers.

---

## SD2 — SQLite Schema Drift in Maintenance Scripts

**Mechanism:** Scripts that embed hardcoded table/column names fail silently (or with
`OperationalError`) when the schema evolves. The script imports fine; error only fires
when the stale name is hit.

**Concrete instance (anonymized):**
```python
# LLM-written script assumed wrong column name:
conn = sqlite3.connect("pipeline.db")
# Actual column is 'created_at', not 'timestamp':
rows = conn.execute("SELECT * FROM jobs WHERE timestamp > ?", (cutoff,)).fetchall()
# OperationalError: no such column: timestamp
```

**Fix rule:** Before writing any maintenance script, verify the live schema:
```bash
sqlite3 your.db "PRAGMA table_info(your_table);"
sqlite3 your.db ".tables"
```
Never hardcode column names without reading them from PRAGMA first.

---

## SD3 — Plain Counter Promoted to LabeledCounter Breaks All Callers

**Mechanism:** `Counter("name", "help")` returns a plain Counter with `.inc()`.
`Counter("name", "help", ["label"])` returns a LabeledCounter requiring
`.labels(l="v").inc()`. Adding labels is not backward-compatible.

**Concrete instance (anonymized):**
```python
# Before:
errors_total = Counter("errors_total", "Total errors")
errors_total.inc()   # works

# LLM adds a label:
errors_total = Counter("errors_total", "Total errors", ["error_type"])
errors_total.inc()   # TypeError: can't use inc() on labeled counter
# All existing call sites now break
```

**Detection:**
```bash
# Find all usages before adding labels:
grep -rn "errors_total\|your_metric_name" --include="*.py" .
# Check every .inc(), ._value, etc. — all need updating
```

**Fix rule:** Before adding labels to any metric, grep all usages. Update all call
sites atomically in the same commit.

---

## SD4 — YAML Multi-Document Missing `---` Separator

**Mechanism:** Adjacent YAML documents without a `---` separator merge into one
malformed object. `yaml.safe_load_all()` returns one doc instead of N; lookups
on the merged doc return unexpected results.

**Concrete instance (anonymized):**
```yaml
# LLM forgot the --- separator between two k8s manifests:
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  LOG_LEVEL: info
apiVersion: v1          # ← should have --- before this
kind: Secret
metadata:
  name: app-secret
```

```python
docs = list(yaml.safe_load_all(open("manifests.yaml")))
# Returns 1 doc instead of 2 — both merged into malformed object
configs = [d for d in docs if d.get("kind") == "ConfigMap"]  # []
```

**Fix rule:**
```bash
python3 -c "import yaml; docs=list(yaml.safe_load_all(open('manifests.yaml'))); print(len(docs), 'docs')"
```
Expected count = number of `---` separators + 1.
