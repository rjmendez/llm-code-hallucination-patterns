# TEC — Test Environment Contamination Patterns

Test env contamination: the test environment itself is wrong, biasing results without
the test code being wrong.

---

## TEC1 — Shared Prometheus Registry State Leak Between Tests

**Mechanism:** Prometheus counters/gauges are process-global. A test that increments a
counter leaks that value into every subsequent test in the same pytest process.

**Symptom:** `assert 2 == 1` or `assert 0.66 == 0.0` for metric values — expected
value is isolated starting state but actual includes prior test residue.

**Concrete instance (anonymized):**
```python
# test_a.py runs first, increments the counter twice:
def test_process_two_events():
    pipeline.process(event_a)
    pipeline.process(event_b)
    assert metrics.events_total._value.get() == 2  # passes

# test_b.py expects a fresh counter:
def test_process_one_event():
    pipeline.process(event_c)
    assert metrics.events_total._value.get() == 1  # FAILS: actual is 3 (leaked from test_a)
```

**Fix options:**
```python
# Option 1: Re-initialize the registry in fixture
@pytest.fixture(autouse=True)
def reset_metrics():
    PipelineMetrics._initialized = False
    PipelineMetrics._init_metrics()
    yield

# Option 2: Mock the metrics class entirely
@pytest.fixture
def mock_metrics():
    with mock.patch("myapp.metrics.PipelineMetrics") as m:
        yield m
```

Note: prometheus_client intentionally prevents Counter decrement.
Gauges CAN be reset with `.set(0.0)`.

---

## TEC2 — git stash Baseline Count is Misleading

**Mechanism:** `git stash` hides ALL working-tree changes including files you didn't
touch. Stash-run failure count may be lower than the real baseline if stashed files
had pre-existing failures.

**Fix rule:**
```bash
# Record actual baseline BEFORE any changes:
git diff --name-only   # what's already modified
python3 -m pytest --tb=no -q 2>&1 | tail -3   # real baseline count

# Do NOT use post-stash count as authoritative before-state
```
