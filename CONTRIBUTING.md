# Contributing

## Adding a New Sample

1. Copy `samples/schema.json` as your template
2. Fill in all fields — use ONLY synthetic/anonymized code
3. **Do not include:** real project names, real variable names, real company names,
   real API keys, real endpoints, real credentials, or any code that could identify
   a private codebase
4. Save to `samples/<anonymized-system-name>/NNN-pattern-id.json`
5. Add your entry to `samples/index.json`
6. Open a PR with a description of the failure mode and how you observed it

## Adding a New Pattern

New patterns must:
- Have a distinct, reproducible failure shape
- Have at least one concrete production codebase instance (anonymized)
- Have a detection method (grep command, ruff rule, or runtime check)
- Have a fix rule (not just "don't do this")
- Not be a duplicate of an existing pattern (check the index table in README)

File: `patterns/<CATEGORY>-<name>.md`

Template:
```markdown
## CATEGORY_ID — Pattern Name

**Mechanism:** One sentence describing what goes wrong and why.

**Symptom:** What the engineer observes. Not the root cause — the first visible sign.

**Concrete instance (anonymized):** A fabricated but structurally-faithful example.

**Detection:**
\`\`\`bash
# grep or ruff command
\`\`\`

**Fix rule:** What to do instead. Must be actionable.

**Cross-references:** Other patterns this commonly co-occurs with.
```

## Reporting a Pattern Without a PR

Open an issue using the "New Pattern" template in `.github/ISSUE_TEMPLATE/`.

## Code of Conduct

Be constructive. This repo exists to make software more reliable, not to critique
any particular LLM vendor, coding assistant, or team.
