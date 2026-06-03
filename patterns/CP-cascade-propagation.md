# CP — Cascade Propagation Patterns

Cascade propagation: one change has N secondary impact sites that are invisible until
you look for them. The initial change is correct; the failures appear in unrelated files.

---

## CP1 — API Signature Change: Compiler Surfaces One Call Site at a Time

**Mechanism:** In compiled languages (Rust, Java, Kotlin, Go), changing a method
signature causes the compiler to report the FIRST mismatched call site per build cycle.
The naive fix loop: fix site A → build → fix site B → build → N builds for N callers.

**Concrete instance (anonymized):**
```rust
// Before:
fn process_event(event: Event) -> Result<()>

// After (new required param):
fn process_event(event: Event, context: &Context) -> Result<()>

// Compiler reports one error at a time:
// error[E0061]: this function takes 2 arguments but 1 argument was supplied
//   --> src/handler_a.rs:45
// (fix A, rebuild...)
//   --> src/handler_b.rs:23
// (fix B, rebuild...)
// ...N cycles for N callers
```

**Fix rule:**
```bash
# Before fixing the first reported caller, grep ALL callers:
grep -rn "process_event(" src/ | grep -v "fn process_event"
# Fix all occurrences in one pass, then rebuild once
```

---

## CP2 — Wiring Patch Secondary Impact Cascade (Interface Impact Scan)

**Mechanism:** Any patch that wires a previously-dead code path, adds dataclass fields,
adds metric labels, or inserts SQL columns has at least 5 secondary impact mechanisms,
each breaking different tests silently.

The five failure modes to check for every wiring patch:

**POSITIONAL BREAK** — Does any test assert by numeric index `[N]` on a tuple/list?
Inserting a field mid-dataclass shifts every `[N]` after the insertion point.
Rule: new optional fields go at the END.

**LABEL/SHAPE BREAK** — Does any test use a metric without label kwargs?
Adding labels to a Counter changes its object type — plain `Counter` != `LabeledCounter`.

**GLOBAL STATE LEAK** — Is the metric/registry/singleton process-global?
Prometheus registry persists across tests. Add explicit resets in fixtures.

**LOGIC ORDER BREAK** — Did you add validation AFTER an early-return guard?
Input validation belongs BEFORE config/connection guards.

**FILTER SWALLOWING STIMULI** — Did you add dedup/rate-limiting?
Tests that submit identical payloads to trigger a condition will be silently absorbed.

**Detection (run before any wiring patch):**
```bash
# 1. List every changed symbol
git diff --cached | grep "^+.*\(def \|class \|    [a-z_]*:\)" | grep -v "^+++"

# 2. For each changed symbol, find all test references
grep -rn "ChangedClassName\|changed_method_name" --include="test_*.py" .

# 3. Check each test file for the five failure modes above
```
