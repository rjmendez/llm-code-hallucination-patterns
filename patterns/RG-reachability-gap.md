# RG — Reachability Gap Patterns

Reachability gap: code is unreachable but nothing reports it, or reachable but
reported dead. Both stem from the same root cause — the analyser's model of what
counts as an *entry point* does not match the program's actual entry points.

Dead-code detection is graph reachability from a root set. Finding unreferenced
symbols is the easy half; enumerating the roots is the hard half. LLM-generated
code makes this worse in a specific way: an assistant asked to "remove unused
code" runs a static tool, trusts its output, and either deletes a live entry
point or adds a suppression entry that permanently blinds the check.

**Distinction from WG (Wiring Gap).** WG covers code that *is* called and does
nothing observable — statically live, semantically inert. RG covers code that is
never called at all, and the tooling failures around detecting it. A symbol can
be a WG instance and an RG false negative simultaneously.

---

## RG1 — Registry-Registered Symbol Reported Unreachable

**Mechanism:** A function is registered with a framework rather than called by
name — a decorator (`@app.route`, `@registry.action()`, `@task`), or passed by
reference into a registration call. No source line names it as a callee, so a
static analyser reports it unused. The engineer (or the assistant) then deletes
it, or suppresses it.

**Symptom:** Either a route/tool/handler disappears in production while every
test passes, or the suppression list grows by one more entry per release.

**Concrete instance (anonymized):**
```python
# module_a.py — 40 registered by decorator
@registry.action()
def summarize_records(scope: str) -> str:
    ...

# module_b.py — 11 more registered by reference, not by decorator
def attach(registry, get_store):
    for fn in (rebuild_index, export_snapshot, prune_orphans):
        registry.action()(fn)

# A static pass reports all 51 as unused: nothing "calls" them.
# Deleting rebuild_index breaks production. Nothing fails in CI, because the
# only test asserts the registry is non-empty.
```

**Detection:**
```bash
# Enumerate roots BEFORE computing reachability. Three classes to collect:
#   1. decorated definitions
grep -rn "^@[a-z_]*\.\(route\|action\|tool\|task\|command\|resource\)" --include="*.py" .
#   2. bare names passed into registration calls (tuple/list literals)
grep -rn "for fn in (\|register(\|\.add_handler(\|handlers = \[" --include="*.py" .
#   3. names referenced anywhere under tests/
```
A symbol is a candidate only if it is absent from all three root classes *and*
from every string literal (a string may be a `getattr` dispatch target).

**Fix rule:** Make registration statically visible. Prefer an explicit module-level
`__all__`-style manifest, or a single registration tuple the analyser can read, over
scattered decorators. Where the framework requires decorators, teach the analyser
the decorator name — do not suppress the symbol. Add one test that asserts the
registered count, so a lost entry point fails CI instead of production.

**Cross-references:** WG1, WG2 (registered-but-inert), CP1 (secondary impact sites).

---

## RG2 — Framework Override Reported Unreachable

**Mechanism:** A method overrides a base-class hook that the framework invokes —
`handle_error`, `setUp`, `default`, `__init_subclass__`, `visit_*` on a visitor.
The call is dynamic, through the base class. No source line names the override,
so it reports as dead.

**Symptom:** Deleting it silently restores the *base class* behaviour. Nothing
raises; behaviour changes. An error handler that swallowed per-request faults is
removed, and a single bad request now takes down a worker.

**Concrete instance (anonymized):**
```python
class WorkerServer(socketserver.ThreadingUnixStreamServer):
    def handle_error(self, request, client_address) -> None:
        # Framework calls this. Nothing in the codebase does.
        # A reachability pass with no base-class model reports it unused.
        pass
```

**Detection:**
```bash
# Any def whose name matches a method on an ancestor class is framework-reachable.
# Cheap approximation without full type resolution: treat every method defined in
# a class that has ANY base class as a root unless the name is project-unique.
grep -rn "class .*(.*):" --include="*.py" .
```

**Fix rule:** Resolve base classes and treat every method that shadows an inherited
name as a root. When the base class is third-party and unresolvable, mark the symbol
`uncertain` rather than `dead` — a reachability tool must have three outcomes, not
two. Never let "unproven reachable" print as "dead".

**Cross-references:** RG1, SL2 (lifetime assumptions).

---

## RG3 — Suppression List Outlives Its Reason

**Mechanism:** A dead-code tool emits false positives (usually RG1 or RG2). Rather
than fix the root model, entries are added to an allowlist. The list is append-only
in practice: nothing ever re-checks whether an entry is still needed. Over time it
accumulates names that have since become *genuinely* dead — and now suppresses them.
The check reports clean while dead code accumulates behind it.

**Symptom:** A dead-code job that has passed for months, in a codebase visibly
carrying dead code. The failure is the *absence* of a signal, so nothing surfaces it.

**Concrete instance (anonymized):**
```python
# deadcode_allowlist.py — entries accumulate, none are ever removed
summarize_records      # added: false positive, decorator-registered
rebuild_index          # added: false positive, registered by reference
legacy_export          # added 14 months ago; the caller was deleted 9 months ago.
                       # This is now genuinely dead and permanently invisible.
```

**Symptom in numbers (anonymized, one service):** the allowlist suppressed 97
findings. Re-running with correct root enumeration and no allowlist produced 8
candidates, of which 6 were real — meaning the allowlist was hiding true positives
inside an overwhelming majority of false ones.

**Detection:**
```bash
# Every allowlist entry is a claim with an expiry. Verify each still needs to exist:
# for each NAME in the allowlist, if NAME is absent from all root classes AND has
# no non-definition reference, the entry is now suppressing genuine dead code.
```

**Fix rule:** Treat suppression entries as expiring assertions. Each must carry a
reason and be re-validated in CI — an entry that no longer corresponds to a live
false positive should fail the build as stale, exactly as an unused suppression in a
type checker does. Better: fix the root enumeration so the entry is unnecessary.
Measure the tool by precision on a known-dead ground-truth set before trusting it;
a detector whose output you routinely suppress is not a detector.

**Cross-references:** RG1, RG2, OG (observability gap — evidence never recorded),
TEC1 (the check environment biasing the result).
