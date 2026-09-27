---
name: variant-analysis
description: Find other manifestations of a confirmed bug or vulnerability across the repository. Use when investigating a known root cause in related modules or designing a matching static-analysis rule; not for general review without a known pattern.
---
# Variant Analysis

## Galaris integration

Begin with the confirmed root cause and the authorized search scope. Use `rg` first; inspect
contracts and callers across the relevant app/core/bridge boundaries before classifying a match.
Distinguish confirmed variants from unverified candidates and false positives. Finding a variant
does not authorize unrelated repairs. Use available tools directly; this standalone skill does
not install plugin commands or authorize parallel agents. CodeQL/Semgrep examples are starting
points requiring validation, not ready-made proof that a finding is exploitable.
Keep diagnostic reports under `artifacts/` or outside the source tree, with synthetic examples
and no secrets or production data. Follow `general` for containerized tool execution.

Find the other instances of a bug you have already found. One root cause usually has several
manifestations, and they are rarely in the module where you found the first one.

## When to Use

- A vulnerability has been found and you need to search for similar instances
- Building or refining CodeQL/Semgrep queries for security patterns
- Performing systematic code audits after an initial issue discovery
- Analyzing how a single root cause manifests in different code paths

## When NOT to Use

- Initial vulnerability discovery without a confirmed pattern
- General code review with no known pattern to search for
- Implementing fixes outside the authorized task
- Understanding unfamiliar code without first identifying the relevant contracts

## The Five Steps

Read the reference for a step when you reach it.

**1. Understand the original issue.** Extract the root cause — why the code is wrong, not
what it does — and enumerate the directions a variant could hide in: related identifiers,
other manifestations of the same mistake, data-type edge cases.
→ [references/root-cause.md](references/root-cause.md)

**2. Create an exact match.** Write a pattern matching ONLY the known instance and confirm
it hits. A pattern that matches nothing means you have misunderstood the bug, and every
search built on it is calibrated against the wrong code.

**3–4. Generalize one element at a time.** Climb from the exact match toward the pattern
family, running and reading all matches after each single change. Stop when more than half
the matches are noise.
→ [references/searching.md](references/searching.md) — abstraction ladder, tool selection,
false-positive filters

**5. Triage.** Decide which candidates are real, and say so with a severity attached.
→ [references/triage.md](references/triage.md)

**Then write it up**, including patterns that failed and, where justified and in scope, a proposed regression guard.
→ [references/reporting.md](references/reporting.md)

## What Makes Hunts Fail

1. **Narrow scope** — searching only the module the original bug was in
2. **Pattern too specific** — searching one attribute and missing the family around it
3. **One vulnerability class** — chasing a single manifestation of the root cause
4. **Happy-path testing** — never trying the null, empty, and boundary cases
5. **Generalizing too fast** — abstracting several elements at once, so noise cannot be
   attributed to any one of them

The first three are covered in root-cause.md and searching.md, the fourth in triage.md.

## Resources

**CodeQL** (`resources/codeql/`): `python.ql`, `javascript.ql`, `java.ql`, `go.ql`, `cpp.ql`

**Semgrep** (`resources/semgrep/`): `python.yaml`, `javascript.yaml`, `java.yaml`, `go.yaml`, `cpp.yaml`

**Report**: `resources/variant-report-template.md`

## Provenance

See [SOURCE.md](SOURCE.md) for the pinned upstream revision, license, and local changes.
