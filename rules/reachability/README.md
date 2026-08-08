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
dead-code tool. On one service (≈520 definitions, a plugin-style server whose
entry points are registered rather than called):

| | result |
|---|---|
| general-purpose static pass, no allowlist | 97 findings |
| same, with the project's allowlist | mostly framework entry points — route handlers and registry-attached functions, i.e. false positives |
| this script | **2 dead, 2 uncertain, 0 false positives in `dead`** |

The three symbols independently confirmed dead by a separate review of that
codebase all appeared in this script's `dead` output before they were removed —
rediscovering known-dead code is the check that makes it a method rather than a guess.

During development this script reported a live `@app.custom_route`-decorated
handler as dead: exactly the RG1 failure it exists to detect. That is why unknown
decorators now demote to `uncertain`.

## What this does not find

Code that **is** called and does nothing observable — statically live, semantically
inert. That is [WG1/WG2](../../patterns/WG-wiring-gap.md), and reachability cannot
see it. Neither can line coverage: such code is covered and still wrong. Catching it
needs a behavioural assertion — mutation testing is the practical tool.
