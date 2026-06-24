# CF — Context Failure Patterns

Context failure: an LLM is given incorrect, stale, or excessive context and generates
code that is internally coherent with that context but wrong for the actual codebase.

Empirical grounding (CrossCodeEval, arXiv:2408.xxxxx): without cross-file context,
exact-match accuracy is 8.82%. With BM25 retrieval: 15.72%. With oracle compact
context: 21.01%. More retrieved context is not always better — at ~50K tokens,
performance degrades even in 200K-window models ("context rot"). SWE-ContextBench
found Free Summary Learning (22.22% pass@1) was *worse* than no-context (26.26%);
oracle compact summaries of 217 tokens avg achieved 34.34%.

---

## CF1 — RAG Bleed: Retrieved Context From Wrong Target

**Mechanism:** A vector search retrieves semantically similar chunks from a different
class, module, or user session. The LLM generates code that is valid for the retrieved
context but wrong for the actual target. No error at generation time — the hallucination
is semantically plausible.

**Symptom:** Generated code uses a method signature or field name that exists in a
related class but not the target class. Compiles and passes type checking; fails at
runtime on the actual instance.

**Concrete instance (anonymized):**
```python
# BAD — RAG retrieves OrderService context when generating InvoiceService method
# OrderService.get(order_id: str) → Order
# InvoiceService.fetch(invoice_ref: int) → Invoice

# Generated (wrong) — adopted OrderService's API signature
class InvoiceService:
    def get(self, invoice_id: str) -> Invoice:   # wrong name, wrong type, wrong param
        return self.db.query(Invoice).filter_by(id=invoice_id).first()
```

```python
# GOOD — retrieve context scoped to the exact target class
# Use filtered retrieval: search only within the same module or tag the chunks
# with class names and filter before including in context.
```

**Detection:**
```bash
# For RAG systems: verify retrieval filter scopes
grep -rn "similarity_search\|vector_store.search\|retrieve\|qdrant.*search" . --include="*.py"
# For each: does the call include a filter on class/module/session?
# Missing filter = bleed risk
```

**Fix rule:** Scope all retrieval operations to the target entity (class, module, user,
session). Store chunk metadata (source class, module path) and filter on it.
Do not include chunks with relevance score below a validated threshold.

---

## CF2 — Stale Context Injection

**Mechanism:** An embedding index or cache is not invalidated after the codebase changes.
Retrieval returns chunks that describe the pre-refactor API. Generated code uses old
method names, old field names, or a removed class. The stale chunk is semantically
similar to the real query (both are about the same subsystem) so it ranks highly.

**Symptom:** Generated code uses a method or class name that was renamed or removed in
a recent commit. The code compiles if the old name is still in scope (as an alias or
test helper); fails at integration.

**Concrete instance (anonymized):**
```python
# After refactor: UserManager.find_by_email() renamed to UserManager.lookup(email=...)
# Stale embedding still describes find_by_email()

# Generated code (from stale context):
user = user_manager.find_by_email(email)   # AttributeError at runtime
```

**Detection:**
```bash
# Find embedding index build timestamps vs last code change
git log --oneline --since="1 week ago" -- '*.py' '*.ts'  # recent changes
# Compare to when the embedding index was last rebuilt
# If index is older than significant API changes → stale context risk
```

**Fix rule:** Rebuild the embedding index after every commit that touches exported APIs.
Add a CI step that flags stale indices. Tag embeddings with the git commit hash they
were built from; reject chunks with a commit hash older than the last API-changing
commit on the relevant path.

---

## CF3 — Context Window Overflow (Context Rot)

**Mechanism:** A retrieval pipeline concatenates chunks without a token budget. For
large codebases, total retrieved context can exceed 50K tokens. Research (CrossCodeEval,
SWE-ContextBench) shows LLM performance degrades past this threshold even with 200K+
context windows — "context rot". Coherent haystacks (related content grouped together)
cause *more* attention degradation than shuffled ones.

**Symptom:** Generated code ignores critical constraints or instructions that were
present in the context but positioned past the ~50K token mark. The model "remembers"
early context better than late context; important constraints are silently dropped.

**Concrete instance (anonymized):**
```python
# BAD — no token budget on retrieved context
def build_prompt(query: str, repo_chunks: list[str]) -> str:
    context = "\n\n".join(repo_chunks)  # could be 200K+ tokens
    return f"Context:\n{context}\n\nQuery: {query}"

# GOOD — enforce a budget
MAX_CONTEXT_TOKENS = 40_000  # well below the rot threshold
def build_prompt(query: str, repo_chunks: list[str], tokenizer) -> str:
    budget = MAX_CONTEXT_TOKENS
    selected = []
    for chunk in repo_chunks:  # ranked by relevance, highest first
        tokens = len(tokenizer.encode(chunk))
        if tokens > budget:
            break
        selected.append(chunk)
        budget -= tokens
    return f"Context:\n{''.join(selected)}\n\nQuery: {query}"
```

**Detection:**
```bash
# Find context assembly without a length check
grep -rn '"\\n\\n".join\|"".join\|context\s*=\s*"\n".join' . --include="*.py"
# For each: is there a token budget applied before assembly?
# Missing budget = context rot risk at scale
```

**Fix rule:** Cap retrieved context at ≤40K tokens. Prefer oracle-style compact
summaries (≤300 tokens per entity) over full file inclusion. SWE-ContextBench showed
217-token summaries outperformed full-file inclusion by +12 percentage points.

---

## CF4 — Silent Context Truncation

**Mechanism:** A retrieval or chunking framework silently truncates its results to a
maximum count or token limit. The most relevant chunk (e.g., the one that defines the
actual interface) is position #N in the ranked list. If N > the truncation limit, it
is silently excluded. No error is raised; the prompt is generated with incomplete
context, and the model generates a plausible but wrong implementation.

**Symptom:** The generated code is correct for the subset of context included but misses
a constraint or interface defined in the truncated chunks. The truncation is invisible
unless the developer audits what was actually included in the prompt.

**Concrete instance (anonymized):**
```python
# BAD — silent truncation, no log of what was dropped
results = vector_store.similarity_search(query, k=5)
# Interface definition was chunk #7; silently excluded

# GOOD — log what was retrieved and what was dropped
results = vector_store.similarity_search(query, k=20)  # fetch more
log.debug("Retrieved %d chunks; top scores: %s", len(results),
          [r.metadata.get("score") for r in results[:5]])
included = results[:MAX_CHUNKS]
excluded = results[MAX_CHUNKS:]
if excluded:
    log.info("Truncated %d chunks from context; lowest included score: %.3f",
             len(excluded), included[-1].metadata.get("score", 0))
```

**Detection:**
```bash
# Find similarity_search / retrieve calls with a hard k= limit
grep -rn "similarity_search\|retrieve.*k=\|top_k=" . --include="*.py"
# For each: is there logging of how many results were retrieved vs included?
# Missing log = silent truncation risk
```

**Fix rule:** Always log the number of chunks retrieved and how many were included vs
excluded. Validate that the key interface chunk (the one defining the target entity's
contract) is in the included set before generating. If not, increase k or use a
targeted lookup for that specific entity.
