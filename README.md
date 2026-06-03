# LLM Code Hallucination Patterns

A taxonomy of systematic failure modes in LLM-generated code, with real-world
samples and static analysis rules for detection.

LLMs generate plausible-looking code that fails in predictable, classifiable ways.
This repository documents those patterns from production codebases so they can be
recognized, detected by tooling, and taught.

---

## Taxonomy

| ID  | Category                    | Patterns | Description |
|-----|-----------------------------|----------|-------------|
| H   | Hallucination               | H1–H9    | Code that looks right but references things that don't exist or changed |
| SD  | Schema Drift                | SD1–SD4  | Structural contracts change in one place; assumptions elsewhere break silently |
| SS  | Silent Swallowing           | SS1–SS6  | Bad input accepted; plausible-but-wrong result returned with no error |
| CP  | Cascade Propagation         | CP1–CP2  | One change has N invisible secondary impact sites |
| SL  | Scope / Lifetime            | SL1–SL2  | Resource alive at definition, dead at point of use (or vice versa) |
| SB  | Serialization Boundary      | SB1–SB2  | Valid Python in memory; fails when crossing a wire (JSON, DB, HTTP) |
| AC  | Async / Concurrency         | AC1–AC4  | Incorrect async patterns, missing circuit breakers, lost exceptions |
| TEC | Test Env Contamination      | TEC1–TEC2 | The test environment itself biases results |
| AT  | Agent Tooling               | AT1–AT6  | Failure modes specific to LLM agent tools (patch, execute_code, terminal) |
| PB  | Parse Boundary              | PB1–PB4  | Validation scattered or deferred past mutation points |
| MF  | Metastable Failure          | MF1–MF3  | Trigger resolves; sustaining feedback loop keeps system stuck |
| DC  | Distributed Consistency     | DC1–DC4  | Stale reads, split singletons, lost writes in multi-component systems |
| CD  | Configuration Drift         | CD1–CD3  | Code correct; config wrong for the deployment environment |
| OG  | Observability Gap           | OG1–OG4  | Bug exists; evidence was architecturally never recorded |
| WG  | Wiring Gap                  | WG1      | Component named for integration it never actually calls |
| MC  | Metric Misconfiguration     | MC1–MC1b | Metric declaration structurally correct but semantically useless |

**Total: 52 documented patterns**

---

## Quick Start

**Debugging LLM-generated code?** Use the [checklist](rules/checklist.md) — it maps
symptom patterns to likely categories so you can jump to the right pattern file.

**Want to contribute?** See [CONTRIBUTING.md](CONTRIBUTING.md) and the [sample schema](samples/schema.json).

**Running static analysis?** See the [ruff plugin](rules/ruff_plugin/) for H1, H3, H7, H9 checks.

---

## Why This Taxonomy Exists

Existing benchmarks (EvalPlus, SWE-bench, CodeHalu) measure whether LLM-generated
code is *correct*. They don't classify *how* it fails. This taxonomy was built by
analyzing actual failures across production Python codebases generated with LLM
assistance over a multi-month period.

The patterns fall into three tiers by how hard they are to find:

**Tier 1 — Detected by linters/type checkers:**
H3 (missing import), H7 (vacuous test), SL1 (UnboundLocalError), AC1 (deprecated API)

**Tier 2 — Detected by tests with good coverage:**
H1 (private attr), H2 (registry collision), H8 (type shape mismatch), SD1–SD3, SS1–SS5

**Tier 3 — Only visible in production or integration:**
H4 (None chain), MF1–MF3, DC1–DC4, OG1–OG4, WG1, CD1–CD3

Most LLM code review focuses on Tier 1. Tier 3 is where the real production failures live.

---

## How This Differs from Prior Work

| Work | Categories | Focus | Scope |
|------|-----------|-------|-------|
| [CodeHalu](https://arxiv.org/abs/2405.00253) | 4 | LLM hallucination in generated code | Benchmark / dataset |
| [HalluCode](https://arxiv.org/abs/2401.10509) | ~5 | Fabricated imports/methods | LLM evaluation |
| [EvalPlus](https://arxiv.org/abs/2305.01210) | N/A | Functional correctness | Benchmark |
| [SWE-bench](https://arxiv.org/abs/2310.06770) | N/A | Real GitHub issue resolution | Agent benchmark |
| **This repo** | **52 patterns in 16 categories** | Operational taxonomy + samples | Production debugging |

Key differences:
- Covers agent-specific failures (AT patterns) unstudied elsewhere
- Covers production-only failures (MF, OG, WG, CD) no benchmark can observe
- Each pattern has real codebase instances, bad/good code pairs, and detection commands
- Growing labeled sample corpus for training and evaluation

---

## Pattern Files

- [H: Hallucination](patterns/H-hallucination.md)
- [SD: Schema Drift](patterns/SD-schema-drift.md)
- [SS: Silent Swallowing](patterns/SS-silent-swallowing.md)
- [CP: Cascade Propagation](patterns/CP-cascade-propagation.md)
- [SL: Scope / Lifetime](patterns/SL-scope-lifetime.md)
- [SB: Serialization Boundary](patterns/SB-serialization-boundary.md)
- [AC: Async / Concurrency](patterns/AC-async-concurrency.md)
- [TEC: Test Env Contamination](patterns/TEC-test-contamination.md)
- [AT: Agent Tooling](patterns/AT-agent-tooling.md)
- [PB: Parse Boundary](patterns/PB-parse-boundary.md)
- [MF: Metastable Failure](patterns/MF-metastable-failure.md)
- [DC: Distributed Consistency](patterns/DC-distributed-consistency.md)
- [CD: Configuration Drift](patterns/CD-configuration-drift.md)
- [OG: Observability Gap](patterns/OG-observability-gap.md)
- [WG: Wiring Gap](patterns/WG-wiring-gap.md)
- [MC: Metric Misconfiguration](patterns/MC-metric-misconfiguration.md)

---

## Samples

Real-world instances of these patterns from anonymized production codebases.
See [samples/](samples/) and the [submission schema](samples/schema.json).

---

## License

MIT. See [LICENSE](LICENSE).

---

## Citation

If you use this taxonomy in research:

```
@misc{llm-code-hallucination-patterns,
  title  = {LLM Code Hallucination Patterns: A Taxonomy of Systematic Failure Modes},
  author = {rjmendez and contributors},
  year   = {2026},
  url    = {https://github.com/rjmendez/llm-code-hallucination-patterns}
}
```
