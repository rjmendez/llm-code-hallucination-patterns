# AT — Agent Tooling Patterns

Failure modes specific to LLM agents using tools like `patch`, `execute_code`,
`terminal`, and `read_file`. Distinct from code-generation failures because the
agent is acting on a live system.

---

## AT1 — Scoped-Context Blindness: Tool Result Not Read Before Write

**Mechanism:** An agent writes a file without reading it first. If a sibling subagent
or prior turn modified the file, the write overwrites those changes silently.

**Symptom:** File content regresses to an earlier state after an agent run.

**Concrete instance (anonymized):**
```
# Agent generated this sequence (wrong):
WRITE config.yaml  ← no prior read
# File had been patched by user between agent runs; patch is now gone

# Correct sequence:
READ config.yaml   ← verify current state first
PATCH config.yaml  ← targeted change only
# Never write a file without reading it in the same turn
```

**Fix rule:** Agent prompt engineering: "Before writing any file you plan to modify,
read it first. Use `patch` (targeted) not `write_file` (destructive) for existing files."

---

## AT2 — Parallel Subagent Write Conflict

**Mechanism:** Two subagents writing the same file in parallel produce nondeterministic
results — last write wins and earlier changes are lost.

**Concrete instance (anonymized):**
```
Subagent A: writes schema.json (adds 3 fields)
Subagent B: writes schema.json (adds 2 other fields) at same time
Result: schema.json has only Subagent B's changes; A's fields are gone
```

**Fix rule:** Agent orchestration: serialize writes to shared files. Read-read-read
can parallelize; write to the same file must be sequential.

---

## AT3 — `execute_code` Side Effect Persists Across Turns (Global State Mutation)

**Mechanism:** `execute_code` runs Python in a persistent session. Module-level code
that imports, patches, or mutates global state in one turn affects subsequent turns.
Agent "forgets" these mutations when session is compacted.

**Concrete instance (anonymized):**
```python
# Turn 3: agent patches sys.path for a test
import sys; sys.path.insert(0, "/tmp/test_module")

# Turn 7 (after compaction): agent imports the same module
# Gets the TEST version from /tmp/test_module, not the production version
# Produces wrong output; agent doesn't know why
```

**Fix rule:** Treat `execute_code` as isolated. Use `terminal()` for side-effect-free
subprocesses. Avoid mutating `sys.path`, `os.environ`, or global singletons in `execute_code`.

---

## AT4 — Stub Completion Fallacy (Reporting Without Executing)

**Mechanism:** An agent writes a plan, a stub function, or a config file and then
reports "done" without actually running the code or verifying the file produces the
expected result.

**Concrete instance (anonymized):**
```
# Agent wrote database_client.py and reported:
# "The database client is implemented and ready to use"
# But never called python3 -c "from database_client import DatabaseClient"
# DatabaseClient has a syntax error on line 23
```

**Detection:** Always run the artifact before reporting:
```bash
python3 -c "from your_module import YourClass"    # import check
python3 -m pytest tests/test_your_module.py -x    # test check
```

---

## AT5 — Tool Error Message Confabulation

**Mechanism:** When a tool call fails with an unusual error, the agent generates a
plausible-sounding explanation that is wrong. Common example: "File not found" reported
as "The file was successfully deleted as part of the cleanup step."

**Symptom:** Agent's stated reason for a failure doesn't match the actual error.

**Fix rule:** Always quote the literal error message. Never paraphrase an error
without including the verbatim text.

---

## AT6 — Compaction Horizon Amnesia

**Mechanism:** After context compaction, an agent loses awareness of files written,
variables defined, or state established in earlier turns. Restarts tasks already
completed, overwrites correct files, or re-asks questions already answered.

**Concrete instance (anonymized):**
```
# Context compacted after turn 40
# Turn 41: agent asks "Should I create the directory structure?"
# Directory structure was created in turn 8 and confirmed in turn 12
```

**Fix rule:** Compaction summaries should capture: files created (with paths),
config values set, experiments run (with results), user decisions made. Every agent
framework should have a "state checkpoint" pattern before compaction-risk zones.
