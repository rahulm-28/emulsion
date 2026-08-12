---
description: Work out which Emulsion module is next and start its brainstorm → spec flow
---

Start the next module of Emulsion.

## Orient first — do not skip this

1. Read `CLAUDE.md` for the architecture invariants and current module status.
2. Read `docs/superpowers/specs/2026-08-12-m0-foundations-design.md` — the source of truth.
   Pay attention to §4 (multi-model capability manifests) and §13 (research basis); both
   constrain every later module.
3. List `docs/superpowers/specs/` and `docs/superpowers/plans/` to see what actually exists,
   rather than trusting the status table.
4. **Read the previous module's "open items" section.** Every spec ends with one, and it is
   the input to the module you are about to start. Starting without it means re-deriving
   decisions that were already made.
5. If `$ARGUMENTS` names a module, do that one. Otherwise take the next unstarted module in
   order — modules are completed one at a time, in sequence.

## Then

Invoke `superpowers:brainstorming` for that module.

Brainstorm the module only. Not the whole product — that decomposition is already done, and
re-opening it wastes the session. If something genuinely conflicts with M0, say so
explicitly and propose a spec amendment rather than quietly designing around it.

Ask questions one at a time. Lead with a recommendation on every choice.

The module's spec goes to `docs/superpowers/specs/YYYY-MM-DD-<module>-design.md`, and it
must end with its own **open items** section for the module after it.
