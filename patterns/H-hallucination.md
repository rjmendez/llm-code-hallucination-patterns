# H — Hallucination Patterns

LLM generates plausible-looking code that references attributes, APIs, or names
that don't exist, are version-gated, or were never imported.

These are the top-9 observed failure modes from production codebases.

---

## H1 — Private / Internal Attribute Fabrication

**Mechanism:** LLM uses internal attributes like `._value`, `._metrics`, `._internal`
that "look right" but may not exist or changed between library versions.

**Symptom:** `AttributeError` on a private attribute (`._*`) that "should" exist.

**Concrete instance (anonymized):**
```python
# BAD — LLM generated access to ._value on a metrics counter
# prometheus-client's Counter._value API is version-dependent and undocumented
from prometheus_client import Counter

events_total = Counter("events_total", "Total events processed")
events_total.inc()

# LLM wrote this — fails on some prometheus_client versions:
raw_value = events_total._value.get()  # AttributeError: 'Counter' has no attribute '_value'

# GOOD — use the public API
# For testing, use a test registry or mock; for export, let prometheus scrape
```

**Detection:**
```bash
grep -rn "\._[a-z_]*\." --include="*.py" . | grep -v "test_\|#"
# Flag any private attr access on objects you don't own
```

**Fix rule:** Never use private library attributes without reading the library source:
```bash
python3 -c "import inspect, prometheus_client; print(inspect.getsource(prometheus_client.Counter))"
```
If no public API exists for what you need, that's an architectural smell — mock the library
in tests instead of poking internals.

**Detection (ruff):** See `rules/ruff_plugin/llm_hallucination_checks.py` — rule `LH001`.

---

## H2 — Registry Collision (Duplicate Metric Registration)

**Mechanism:** LLM registers a new metric with the same name as an existing one — often
in a module-level singleton that was already registered. Raises at test startup, not at
the metric definition line.

**Symptom:** `ValueError: Duplicated timeseries in CollectorRegistry` at pytest
collection, not where the metric is defined.

**Concrete instance (anonymized):**
```python
# In pipeline_worker.py (already exists):
events_total = Counter("events_total", "Worker events")

# LLM adds in pipeline_monitor.py (new file):
events_total = Counter("events_total", "Monitor events")  # BOOM at import time
# ValueError: Duplicated timeseries in CollectorRegistry: {'events_total'}
```

**Detection:**
```bash
grep -rn "Counter\|Gauge\|Histogram\|Summary" --include="*.py" . \
  | grep '"[a-z_]*"' | sed 's/.*"\([a-z_]*\)".*/\1/' | sort | uniq -d
```

**Fix rule:** Before adding any prometheus metric, grep for its name string. If already
registered, import and reuse the existing object — never re-register.

---

## H3 — Wired-But-Not-Imported Dead Reference

**Mechanism:** LLM adds a function call in one file (the wire-up) but forgets the import.
The code "looks correct" but `NameError` fires at the call site.

**Symptom:** `NameError: name 'SomeClass' is not defined` even though `SomeClass` is
defined elsewhere and "looks imported."

**Concrete instance (anonymized):**
```python
# In orchestrator.py — LLM added wiring call:
def process_event(event):
    result = route(event)
    logger = EventLogger()          # NameError: 'EventLogger' is not defined
    logger.record(result)
    return result

# Missing from imports block:
# from .event_logger import EventLogger   ← LLM forgot this line
```

**Detection:**
```bash
python3 -c "import ast, sys
tree = ast.parse(open('orchestrator.py').read())
names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
imports = {n.name for n in ast.walk(tree) if isinstance(n, ast.alias)}
print('Possibly undefined:', names - imports - set(dir(__builtins__)))"
```

**Fix rule:** After any wiring patch, verify the import block:
```bash
head -30 path/to/wiring_file.py | grep import
```
Every name used at the call site must appear in the import list.

**Detection (ruff):** `F821` (undefined name) — already in ruff core. Enable it.

---

## H4 — Confabulated Method Chain (None Propagation)

**Mechanism:** LLM writes `obj.method_a().method_b().method_c()` where `.method_a()`
can return `None`. The chain looks natural but fails at `.method_b()` with
`AttributeError: 'NoneType' has no attribute 'method_b'`.

**Why it happens:** LLM trains on fluent-interface patterns (jQuery, pandas, SQLAlchemy)
and assumes any method in a chain returns `self` or a non-None value.

**Concrete instance (anonymized):**
```python
# LLM generated a pipeline with chained accessors:
class DataPipeline:
    def get_stage(self, name):
        return self._stages.get(name)   # returns None if key missing

# LLM then chains on the result:
pipeline.get_stage("transform").get_output().to_dict()
# AttributeError: 'NoneType' has no attribute 'get_output'
# when stage "transform" doesn't exist yet
```

**Detection:**
```bash
grep -rn "\.[a-z_]*()\\.[a-z_]*()\\.[a-z_]*()" --include="*.py" .
# Flag chains 3+ deep for manual None-safety review
```

**Fix rule:** Check the return type of the first method before chaining:
```python
stage = pipeline.get_stage("transform")
if stage is None:
    raise ValueError("Stage 'transform' not registered")
output = stage.get_output().to_dict()
```

---

## H5 — Hardcoded Assertion Values from Inference

**Mechanism:** LLM writes `assert result == 0.857` with a value it *inferred* from
reading logic rather than observing actual output. Tests pass at first, fail when an
upstream constant changes.

**Concrete instance (anonymized):**
```python
# LLM inferred that score would be 0.75 based on reading the formula
def test_priority_score():
    item = WorkItem(urgency=3, impact=4, age_days=10)
    score = compute_priority(item)
    assert score == 0.75   # LLM guessed this; actual output is 0.7142857...
    # Test fails immediately on first run
```

**Fix rule:** For any computed value, observe it first:
```bash
python3 -c "from module import compute_priority, WorkItem; \
            print(compute_priority(WorkItem(urgency=3, impact=4, age_days=10)))"
```
Use the observed output. Add a comment: `# observed: 2026-06-03`.

---

## H6 — Frozen-Version API Assumption

**Mechanism:** LLM uses an API it learned during training that has since been deprecated
or removed. Common examples:
- `datetime.utcnow()` — deprecated Python 3.12
- `asyncio.get_event_loop()` — deprecated Python 3.10
- `pkg_resources` — replaced by `importlib.metadata`
- `collections.Callable` — removed Python 3.10

**Concrete instance (anonymized):**
```python
# LLM generated timestamp utility:
from datetime import datetime

def current_timestamp():
    return datetime.utcnow().isoformat()  # DeprecationWarning: 3.12+

# GOOD — timezone-aware:
from datetime import datetime, timezone

def current_timestamp():
    return datetime.now(tz=timezone.utc).isoformat()
```

**Detection:**
```bash
python3 -W error -c "from your_module import your_function" 2>&1 | grep DeprecationWarning
grep -rn "utcnow\|get_event_loop\|pkg_resources\|collections\.Callable" --include="*.py" .
```

---

## H7 — Vacuous Test (Missing Assert)

**Mechanism:** LLM generates a test that calls the function under test but forgets the
`assert`. The test always passes because no assertion ever fires.

**Concrete instance (anonymized):**
```python
# BAD — passes unconditionally; tests nothing
def test_score_calculation():
    result = calculate_score(input_data)
    result == 0.65          # bare comparison, not assertion

# GOOD
def test_score_calculation():
    result = calculate_score(input_data)
    assert result == 0.65
```

**Detection:**
```bash
grep -rn "^\s*[a-z_].*==[^=]" --include="test_*.py" . | grep -v "assert\|#"
```
Or enable ruff rule `B015` (bare comparison used as statement).

---

## H8 — Type Shape Mismatch (Dict vs List vs Tuple)

**Mechanism:** LLM generates a call with the wrong collection type for a parameter.
No `TypeError` fires because Python is duck-typed; the wrong type silently triggers
a conservative default path.

**Symptom:** A boolean method that always returns the same value regardless of inputs.

**Concrete instance (anonymized):**
```python
# Function signature:
def should_escalate(state_list: list[dict], risk_score: float) -> bool:
    if risk_score is None:
        return True  # conservative default
    return any(s["severity"] > 0.8 for s in state_list) and risk_score > 0.7

# LLM generated test passes a dict instead of a list:
result = processor.should_escalate(state_snapshot)   # dict as state_list, risk_score=None
# risk_score defaults to None → method always returns True
# Test always passes but is testing the wrong path
```

**Detection:**
```bash
# Compare production call sites vs test call sites
grep -rn "should_escalate(" --include="*.py" .
# If call sites have different argument counts or types, one is wrong
python3 -c "import inspect; from module import Processor; p = Processor(); print(inspect.signature(p.should_escalate))"
```

---

## H9 — Deferred Async Init Pattern Ignored

**Mechanism:** LLM generates `async def __init__` or relies on `__post_init__` doing
async work. Python forbids async constructors — the async call in `__init__` runs
synchronously and silently returns a coroutine object instead of awaiting.

**Concrete instance (anonymized):**
```python
# BAD — async __init__ is a syntax error in Python
class DatabaseClient:
    async def __init__(self, dsn: str):   # SyntaxError or silent wrong behavior
        self.conn = await asyncpg.connect(dsn)

# Also BAD — asyncio.run() inside async context blocks the event loop
class DatabaseClient:
    def __init__(self, dsn: str):
        self.conn = asyncio.run(asyncpg.connect(dsn))  # RuntimeError if loop running

# GOOD — factory pattern
class DatabaseClient:
    @classmethod
    async def create(cls, dsn: str) -> "DatabaseClient":
        obj = cls.__new__(cls)
        obj.conn = await asyncpg.connect(dsn)
        return obj
```

**Detection:**
```bash
grep -rn "RuntimeWarning: coroutine.*never awaited" tests/ logs/
grep -rn "asyncio\.run(" --include="*.py" . | grep "__init__\|def __"
```
