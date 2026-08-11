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

---

## TEC3 — Instrumented Test Navigates via Side-Channel on a Permanently-GONE View

**Mechanism:** An Espresso (Android) or UI-Automator test interacts with a View that
is permanently `android:visibility="gone"` in the layout. The test's `ViewAction`
either bypasses the `isDisplayed()` constraint check or fires an event listener
directly (e.g., `TabLayout.Tab.select()`) that triggers the navigation side effect
without the View ever being visible. The test passes — it verifies real navigation
state — but it exercises a path that is impossible for a real user.

**Symptom:** Tests pass on CI. Manual QA finds that the navigation gesture the test
exercises (e.g., tapping a tab) is impossible for users because the tab bar is GONE.
The feature the test claims to verify may not be reachable by any user-accessible action.

**Concrete instance (anonymized):**
```java
// EspressoUtils.java — constraint does NOT require isDisplayed():
public static ViewAction selectTabAtPosition(final int position) {
    return new ViewAction() {
        @Override
        public Matcher<View> getConstraints() {
            return isAssignableFrom(TabLayout.class);  // WRONG — allows GONE views
        }
        @Override
        public void perform(UiController uiController, View view) {
            TabLayout.Tab tab = ((TabLayout) view).getTabAt(position);
            tab.select();   // fires OnTabSelectedListener on a GONE view
            uiController.loopMainThreadUntilIdle();
        }
    };
}

// The TabLayout in the layout file:
// android:visibility="gone"   ← users cannot see or tap this
```

```java
// GOOD — constraint requires the View to be visible to the user:
@Override
public Matcher<View> getConstraints() {
    return allOf(isDisplayed(), isAssignableFrom(TabLayout.class));
}
```

**Detection:**
```bash
# Find ViewAction implementations missing isDisplayed() in getConstraints():
grep -rn "getConstraints" androidTest/ --include="*.java" -A5 \
  | grep -v "isDisplayed"

# Find tab.select() / direct listener calls in test code (bypasses UI visibility):
grep -rn "\.select()\|fireOnTabSelected\|onTabSelected" androidTest/ --include="*.java"
```

**Fix rule:**
1. Always include `isDisplayed()` (or `withEffectiveVisibility(VISIBLE)`) in
   `ViewAction.getConstraints()`.
2. If navigation requires a GONE view, the test must use the real production code path
   (e.g., call the Activity method directly via `scenario.onActivity(...)`) with a
   `@VisibleForTesting` annotation — not a side-channel.
3. Add a test that verifies the navigation target is reachable from the UI that
   **is** visible to users.

**Cross-references:** MP1 (platform-specific test trap), WG5 (interactive element with no-op handler)
