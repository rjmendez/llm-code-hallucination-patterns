# MP — Mobile Platform Traps

Platform-specific runtime behavior that silently voids code which looks correct to
a language-level reader. The code compiles, passes host-JVM tests, and has no visible
warning — but on the actual device runtime it is a permanent no-op or compilation error.

---

## MP1 — Java `assert` Statements Permanently Disabled on Android Runtime (ART)

**Mechanism:** Java's `assert` keyword is gated on the JVM flag `-ea` (enable assertions).
Android's ART runtime has no `-ea` equivalent and no mechanism to enable assertions.
Every `assert` statement in Android source code is unconditionally a no-op. LLMs that
generate assertion-heavy test/validation code for Android inherit the host-JVM mental
model and produce code that looks like it validates invariants but does nothing at all.

**Symptom:** A class named `*Test` or `*Validator` in `src/main/java/` contains dozens
of bare `assert` statements. CI passes because assertions never execute. Production
silently violates every invariant the assertions were meant to catch.

**Concrete instance (anonymized):**
```java
// src/main/java/com/example/Phase1BTest.java
// LLM wrote this as validation code, believing assert runs like JUnit:
public class Phase1BTest {
    public static void runAllTests() {
        SceneEngine engine = new SceneEngine();
        assert engine.getWeight() > 0.0f;                  // NO-OP on ART
        assert engine.getExtractors().size() == 5;          // NO-OP on ART
        assert engine.contradiction() < 1.0f;              // NO-OP on ART
    }
    // runAllTests() is also never called from any Activity or test runner
}
```

The correct Android equivalent:
```java
// src/test/java/com/example/Phase1BTest.java (JUnit, runs on host JVM)
public class Phase1BTest {
    @Test
    public void extractorCountIsCorrect() {
        assertEquals(5, new SceneEngine().getExtractors().size());
    }
}
```

**Detection:**
```bash
# Find assert statements in Android src/main (not src/test):
grep -rn "^\s*assert " android/app/src/main/ --include="*.java"

# Find *Test.java files in src/main:
find android/app/src/main -name "*Test.java"
```

**Fix rule:**
1. Move the file to `src/test/java/` (host JVM — assertions enabled by default via JUnit runner).
2. Replace bare `assert condition;` with `assertTrue(condition)` / `assertEquals(expected, actual, delta)`.
3. Add `@Test` annotations and a `@RunWith(JUnit4.class)` runner.
4. Delete the original `src/main/` copy — it will compile into the APK otherwise even without a manifest entry.

**Cross-references:** TEC3 (dead test code in production class), WG4 (code present but never invoked)

---

## MP2 — Kotlin Default Parameters Invisible to Java Without `@JvmOverloads`

**Mechanism:** Kotlin's default parameter feature (`fun f(a: Int, b: Int = 0)`) is
implemented in Kotlin bytecode as a single method with a synthetic `$default` helper.
Java callers see only the fully-specified signature — the default is invisible to Java.
An LLM that generates a Kotlin API with default parameters and a Java call site will
produce code that fails to compile in Java unless `@JvmOverloads` is present.

**Symptom:** A Kotlin function has `@JvmStatic` (indicating Java interop intent) and
a default parameter but no `@JvmOverloads`. The Java call site passes fewer arguments
than the full parameter count. `javac` reports: `no suitable method found for bind(ComposeView, ViewModel, String)`.

**Concrete instance (anonymized):**
```kotlin
// BAD — Java cannot call the 3-arg form
object ViewBinder {
    @JvmStatic
    fun bind(view: ComposeView, vm: ViewModel, nodeId: String, battery: Int = -1) {
        view.setContent { Screen(vm, nodeId, battery) }
    }
}
```
```java
// Java call site (3 args) — COMPILE ERROR: no 3-arg overload visible in bytecode
ViewBinder.bind(composeView, viewModel, nodeId);
```

```kotlin
// GOOD — @JvmOverloads generates Java-visible 3-arg AND 4-arg overloads
object ViewBinder {
    @JvmStatic
    @JvmOverloads
    fun bind(view: ComposeView, vm: ViewModel, nodeId: String, battery: Int = -1) {
        view.setContent { Screen(vm, nodeId, battery) }
    }
}
```

**Detection:**
```bash
# Find @JvmStatic functions with default parameters but no @JvmOverloads:
grep -B3 "fun .*=.*)" android/**/*.kt | grep -B3 "@JvmStatic" | grep -v "@JvmOverloads"

# Or: find all Java call sites to Kotlin object methods and count their arg lists:
grep -rn "\bBinder\.bind\|\bHelper\.\w\+" --include="*.java" android/
# Cross-reference against the Kotlin signature to verify arg count matches
```

**Fix rule:** Any Kotlin function marked `@JvmStatic` that has a default parameter
value MUST also be marked `@JvmOverloads`. Add this as a code review checklist item
whenever a Kotlin API is designed for Java consumption.

**Cross-references:** SD2 (schema drift between language boundaries)

---

## MP3 — Compose `DisposeOnViewTreeLifecycleDestroyed` Keeps Composition Alive on GONE Views

**Mechanism:** Jetpack Compose's `ViewCompositionStrategy.DisposeOnViewTreeLifecycleDestroyed`
ties composition lifetime to the host Activity/Fragment lifecycle — not to the View's
visibility. When the hosting `ComposeView` is set to `View.GONE` (e.g., when the user
navigates away within a single-Activity architecture), the composition continues to run:
StateFlow collectors fire, animation loops tick, coroutines execute — burning CPU and
battery invisibly.

The correct strategy for views that can be GONE while the Activity is alive is
`DisposeOnDetachedFromWindow`, which disposes the composition when the View is removed
from the window hierarchy.

**Symptom:** On a device with an active MQTT/WebSocket data stream, CPU usage doesn't
drop when the user navigates away from the screen hosting the `ComposeView`. Background
coroutines and `LaunchedEffect` blocks continue to run and process data for a UI that
is not visible.

**Concrete instance (anonymized):**
```kotlin
// BAD — composition survives navigation-away (view becomes GONE, Activity stays alive)
object ScreenBinder {
    @JvmStatic
    fun bind(composeView: ComposeView, vm: ViewModel) {
        composeView.setViewCompositionStrategy(
            ViewCompositionStrategy.DisposeOnViewTreeLifecycleDestroyed  // wrong
        )
        composeView.setContent { LiveDataScreen(vm) }
    }
}

// GOOD — composition disposes when view is detached/hidden
object ScreenBinder {
    @JvmStatic
    fun bind(composeView: ComposeView, vm: ViewModel) {
        composeView.setViewCompositionStrategy(
            ViewCompositionStrategy.DisposeOnDetachedFromWindow  // correct for GONE views
        )
        composeView.setContent { LiveDataScreen(vm) }
    }
}
```

**Detection:**
```bash
# Find ComposeView usages with the wrong strategy:
grep -rn "DisposeOnViewTreeLifecycleDestroyed" android/ --include="*.kt"
# For each: check whether the hosting View can be set to GONE while the Activity is alive
grep -rn "setVisibility.*GONE\|visibility = View.GONE" android/ --include="*.java" --include="*.kt"
```

**Fix rule:**
- In a single-Activity app with fragment-less navigation (views toggled via `GONE`/`VISIBLE`):
  use `DisposeOnDetachedFromWindow`.
- In a Fragment-based app where the Fragment is destroyed on back-press:
  use `DisposeOnViewTreeLifecycleDestroyed` (Fragment's lifecycle matches).
- Rule of thumb: if the View can become GONE without the surrounding lifecycle owner
  being destroyed, use `DisposeOnDetachedFromWindow`.

**Cross-references:** AC4 (async task exception silently discarded while running in background), OG2 (observability gap — background CPU burn with no visible error)
