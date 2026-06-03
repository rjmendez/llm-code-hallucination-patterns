# ruff_plugin — LLM Hallucination Checks

Standalone AST-based checker for LLM code generation hallucination patterns.

## Rules

| Code   | Pattern | Description |
|--------|---------|-------------|
| LH001  | H1      | Private attribute access on external objects (`obj._attr`) |
| LH007  | H7      | Bare comparison in test function (vacuous assert) |
| LH009  | H9      | `asyncio.run()` called inside async function |

## Usage

```bash
# Check a single file
python3 llm_hallucination_checks.py path/to/generated.py

# Check a directory
python3 llm_hallucination_checks.py src/

# As part of CI
python3 rules/ruff_plugin/llm_hallucination_checks.py src/ tests/ && echo "clean"
```

## Output format

```
src/pipeline.py:45:8: LH001 Private attribute access '_value' on external object...
tests/test_worker.py:23:4: LH007 Bare comparison with no 'assert' — test is vacuous...
```

## Ruff native integration (future)

True ruff plugin support requires compiling via the ruff plugin API (Rust extension).
This module provides equivalent checks as a pure-Python fallback. For ruff-native
integration, see: https://docs.astral.sh/ruff/contributing/

## Contributing new rules

1. Add a `check_lhNNN_name(tree, ...)` function in `llm_hallucination_checks.py`
2. Call it from `check_file()`
3. Add the rule to the table above
4. Add at least one sample JSON in `samples/` using the new pattern ID
