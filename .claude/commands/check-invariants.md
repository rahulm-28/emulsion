---
description: Audit the working tree against Emulsion's M0 architecture invariants
allowed-tools: Agent, Bash
---

Audit the code against Emulsion's eight architecture non-negotiables.

Dispatch the `spec-guardian` agent against the uncommitted working tree, or against
`$ARGUMENTS` if a path, ref, or range is given.

This is not a general code review — it checks only the invariants from
`docs/superpowers/specs/2026-08-12-m0-foundations-design.md`, each of which means a rewrite
rather than a patch if it ships:

1. Every model call is an async job
2. `engine` / `imaging` / `providers` import nothing web
3. No `if model == "..."` — capability manifests are data
4. Image bytes never pass through Python
5. Pixels outside an edited region are byte-identical
6. BYOK keys are write-only
7. Requests carry typed parts, not a prompt string
8. Idempotency keys on job creation

Report confirmed violations only, most severe first. If there are none, say so plainly and
stop — do not pad the report with general observations.
