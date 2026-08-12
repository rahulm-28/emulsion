---
description: Empirically establish what the Azure Foundry gpt-image-2 deployment actually supports
allowed-tools: Agent, Read, Bash
---

Establish what the Foundry `gpt-image-2` deployment actually supports, so the capability
manifest stops containing guesses.

Dispatch the `provider-prober` agent.

## What it must answer

These are M0 §14's open items — M1 cannot write an accurate manifest without them:

1. **`input_fidelity`** — is it accepted on `/images/edits` for this deployment? Earlier
   attempts were rejected. Establish whether that was the *model* or the *api-version*.
2. **`mask`** — is it accepted at all here? Note that even where accepted, `gpt-image-*`
   treats a mask as a soft hint rather than a hard constraint, so a 200 response is not
   evidence it constrained anything. The probe must compare outputs.
3. **api-version divergence** — confirm `2024-02-01` works for `/images/generations` and
   404s on `/images/edits`, and that `2025-04-01-preview` works for edits.
4. **Cost per image at 4K** — real numbers, to seed the manifest's `cost_model`.

If `$ARGUMENTS` names specific questions, probe those instead.

## Constraints

- Credentials come from the environment. Never read `.env`, never print a key.
- Smallest image size that answers each question — probes cost real money.
- One variable per probe.
- Probe scripts go in the scratchpad, not the repo.
- `../gpt-image-2/generate.py` already encodes much of this. Read it first; do not
  rediscover what is already known.

## Output

Manifest-ready YAML fields, each with its evidence, a `confirmed` vs `inferred` confidence
marker, and observed cost. Anything that could not be established stays explicitly
`unverified` — a guess encoded as fact silently degrades every request routed to this model.

Report the findings back. Do not edit the M0 spec — these feed the M1 spec.
