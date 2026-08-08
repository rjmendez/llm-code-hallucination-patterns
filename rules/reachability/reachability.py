#!/usr/bin/env python3
"""Reachability-based dead code detection (patterns RG1-RG3).

Dead code is graph reachability from a root set. Finding unreferenced symbols is
the easy half; enumerating ROOTS is the hard half, and it is where general-purpose
tools produce the false positives that lead to allowlist rot (RG3).

This deliberately reports THREE outcomes, not two:

    dead       no reference, and no root class claims it
    uncertain  cannot prove reachable, but a root heuristic may apply
               (methods of subclasses -- see RG2 -- are the main source)
    live       referenced, or claimed by a root class

"uncertain" exists because printing an unproven symbol as "dead" is what teaches
engineers to suppress the tool instead of fixing it.

Usage:
    reachability.py <src-dir> [--tests DIR] [--decorators route,task,action]

Exit status is always 0: this is an advisory report, not a gate. Gate on a
ground-truth precision measurement instead (see README).
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

# Decorator attribute names that mean "registered with a framework" (RG1).
DEFAULT_DECORATORS = {
    "route", "action", "tool", "task", "command", "resource", "prompt",
    "get", "post", "put", "patch", "delete", "websocket",
    "receiver", "listener", "subscribe", "handler", "step", "fixture",
}


def _decorator_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for d in getattr(node, "decorator_list", []):
        cur = d.func if isinstance(d, ast.Call) else d
        if isinstance(cur, ast.Attribute):
            out.add(cur.attr)
        elif isinstance(cur, ast.Name):
            out.add(cur.id)
    return out


def collect(paths: list[pathlib.Path], decorators: set[str]):
    defs: dict[str, list[str]] = {}
    subclass_methods: set[str] = set()
    decorated_unknown: set[str] = set()
    registered: set[str] = set()
    referenced: set[str] = set()
    strings: set[str] = set()

    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue

        for node in ast.walk(tree):
            # RG2: a method of a class WITH bases may override a framework hook.
            if isinstance(node, ast.ClassDef) and node.bases:
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        subclass_methods.add(child.name)

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.setdefault(node.name, []).append(f"{p}:{node.lineno}")
                names = _decorator_names(node)
                if names & decorators:
                    registered.add(node.name)            # RG1: known decorator root
                elif any(isinstance(d.func if isinstance(d, ast.Call) else d, ast.Attribute)
                         for d in node.decorator_list):
                    # RG1, unknown decorator: `@obj.something(...)` is the shape of
                    # registration against a registry object. We cannot prove it
                    # registers, so this is UNCERTAIN -- never "dead". Projects should
                    # pass their own decorator names via --decorators to promote these
                    # to roots. (This rule exists because an earlier version of this
                    # script reported a live `@app.custom_route`-decorated handler as
                    # dead: exactly the RG1 failure it is meant to detect.)
                    decorated_unknown.add(node.name)

            # RG1: bare names inside tuple/list literals are the usual shape of a
            # registration manifest -- `for fn in (a, b, c): registry.add(fn)`.
            elif isinstance(node, (ast.Tuple, ast.List)):
                for e in node.elts:
                    if isinstance(e, ast.Name):
                        registered.add(e.id)

            elif isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.add(node.value.strip())          # possible getattr target

    return defs, subclass_methods, decorated_unknown, registered, referenced, strings


def names_in(paths: list[pathlib.Path]) -> set[str]:
    out: set[str] = set()
    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                out.add(node.id)
            elif isinstance(node, ast.Attribute):
                out.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value.strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=pathlib.Path)
    ap.add_argument("--tests", type=pathlib.Path, default=None,
                    help="test tree; every name it mentions becomes a root")
    ap.add_argument("--decorators", default="",
                    help="extra comma-separated decorator attribute names")
    args = ap.parse_args()

    decorators = set(DEFAULT_DECORATORS)
    decorators |= {d.strip() for d in args.decorators.split(",") if d.strip()}

    def py(root: pathlib.Path) -> list[pathlib.Path]:
        return [p for p in root.rglob("*.py")
                if ".venv" not in p.parts and "site-packages" not in p.parts]

    src_files = [p for p in py(args.src) if "tests" not in p.parts]
    defs, subclass_methods, decorated_unknown, registered, referenced, strings = collect(src_files, decorators)
    test_names = names_in(py(args.tests)) if args.tests else set()

    roots = registered | test_names
    dead, uncertain = [], []
    for name, locs in sorted(defs.items()):
        if name in roots or name in referenced or name in strings:
            continue
        if name.startswith("__") and name.endswith("__"):
            continue
        risky = name in subclass_methods or name in decorated_unknown
        (uncertain if risky else dead).append((name, locs[0]))

    print(f"definitions={len(defs)}  roots: registered={len(registered)} "
          f"tests={len(test_names)}  subclass-methods={len(subclass_methods)} "
          f"decorated-unknown={len(decorated_unknown)}\n")
    print(f"DEAD ({len(dead)}) -- no reference, no root claims them")
    for name, loc in dead:
        print(f"  {name:44s} {loc}")
    print(f"\nUNCERTAIN ({len(uncertain)}) -- overrides a base-class hook (RG2) or carries an "
          f"unrecognised registration decorator (RG1); resolve before deleting")
    for name, loc in uncertain:
        print(f"  {name:44s} {loc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
