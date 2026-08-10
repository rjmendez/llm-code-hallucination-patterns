# Reachability — dead code detection for RG1–RG3

Dead code is graph reachability from a root set. Finding unreferenced symbols is
easy; enumerating the **roots** is the hard part, and it is where general-purpose
tools generate the false positives that lead to allowlist rot ([RG3](../../patterns/RG-reachability-gap.md)).

## Usage

```bash
python3 reachability.py <src-dir> --tests <test-dir> [--decorators custom_route,job]
```

Pass your project's own registration decorators via `--decorators`. Anything not
recognised is reported **uncertain**, never dead.

## Three outcomes, not two

| outcome | meaning |
|---|---|
| `dead` | no reference; no root class claims it |
| `uncertain` | may override a base-class hook (RG2), carries an unrecognised registration decorator (RG1), or is a method of an exported class (RG4) |
| *(omitted)* | referenced, or claimed by a root class |

`uncertain` is the point. Printing an unproven symbol as "dead" is what teaches
engineers to suppress the tool instead of fixing its root model — and a suppression
list, once appended to, is never re-validated.

## Root classes collected

1. **Decorator registration** — `@app.route`, `@registry.tool()`, … (RG1)
2. **Registration manifests** — bare names in tuple/list literals passed to a
   registrar, e.g. `for fn in (a, b, c): registry.add(fn)` (RG1)
3. **Test references** — every name mentioned anywhere under the test tree
4. **String literals** — conservative guard against `getattr(obj, "name")` dispatch
5. **Exported API** — methods of a class in `__all__` or re-exported from an
   `__init__.py`; external consumers can reach them, so one tree cannot prove
   them unused (RG4)
6. **Subclass methods** — any method of a class with bases may override a
   framework hook; demoted to `uncertain` rather than treated as a root (RG2)

## Validation

Measure precision against a known-dead ground-truth set before trusting any
dead-code tool. Ground truth here is a commit that removed dead code after an
independent human review; the measurement runs against the tree as it stood
*before* that commit — 523 definitions, a plugin-style server whose entry points
are registered rather than called.

| | result |
|---|---|
| general-purpose static pass | 23 unused-callable findings — 4 real, **19 false positives** (precision 17%) |
| — of the false positives: registered entry points (RG1) | 15: 13 registration-decorated handlers, 1 resource, 1 route |
| — framework overrides on a subclass (RG2) | 2 |
| — methods of a class in `__all__` (RG4) | 2 |
| this script | **2 dead — both real, 0 false positives — and 6 uncertain** |

The review confirmed three symbols dead and removed them. This script surfaced all
three: two in `dead`, the third in `uncertain` because it was a method of an
exported class. That split is the design working, not a miss — everything it
called dead was dead, and the one it could not prove was routed to a human rather
than to a delete. Its 6 `uncertain` entries contain 2 of the 3 true positives and
4 live symbols, which is the correct shape for a bucket that means "decide this."

Rediscovering known-dead code is what makes this a method rather than a guess.
Refusing to guess on the rest is what keeps it worth running: a tool with 19 false
positives is one that gets an allowlist (RG3), and an allowlist is how the next
true positive goes unseen.

During development this script reported a live `@app.custom_route`-decorated
handler as dead: exactly the RG1 failure it exists to detect. That is why unknown
decorators now demote to `uncertain`.

## What this does not find

**Dead symbols masked by a live namesake.** The graph is keyed on bare names, not
on qualified ones, so a reference to *any* `foo` marks *every* `foo` reachable. In
the validation codebase a module-level `_enclosing_class_id` in one module was
dead while an identically-named nested function in another was live and called;
the live reference covered for the dead definition and it never appeared in the
output. Name-keying is what makes the script short and dependency-free, and this
is its price: it fails toward "live", so it under-reports rather than proposing a
bad delete. Resolving it needs qualified names — module path plus symbol — and an
import graph to bind references to definitions.

**Mutually-referencing dead code.** Two dead functions that call each other are
each "referenced", so neither is reported. A single pass cannot see the cycle;
iterating to a fixed point can.

**Code that is called and does nothing observable** — statically live, semantically
inert. That is [WG1/WG2](../../patterns/WG-wiring-gap.md), and reachability cannot
see it. Neither can line coverage: such code is covered and still wrong. Catching it
needs a behavioural assertion — mutation testing is the practical tool.
