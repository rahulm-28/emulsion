# Working on Emulsion

Human-facing guide. `CLAUDE.md` is the agent-facing one — you don't need to read it, but
it's where the guardrails live.

---

## What this is

An image generation studio: prompt in or attach images to edit, get a result. Accounts,
sessions, image library with version lineage, downloads. Subscriptions or bring-your-own-key.
Multiple models.

The differentiator is the **middleware layer** between the user and the model — prompt
compilation, parameter resolution, candidate ranking, edit routing, post-processing, learned
constraints. Everyone else pipes the prompt straight through to the API.

---

## Where things are

```
docs/superpowers/specs/    design docs — one per module, the source of truth
docs/superpowers/plans/    implementation plans
CLAUDE.md                  agent instructions + architecture guardrails
.claude/settings.json      permissions, so sessions stop asking about safe commands
.claude/agents/            project-specific subagents
.claude/commands/          slash commands
```

A working local application exists in `apps/web`, `services/api`, and `services/worker`,
with shared Python libraries under `packages/`. Run `make install` followed by
`make dev-local` for an isolated free demo, or `make dev` to use your configured services.
The README describes image uploads, structured diagrams, and editing; CLAUDE.md tracks the remaining module work.

---

## Prerequisites

Nothing is needed to *plan* the next module. To eventually run things:

| Tool | Version | Why |
|---|---|---|
| Python | 3.12 | backend, engine, imaging |
| `uv` | latest | Python packages + workspace |
| Node | 22 | frontend |
| `pnpm` | latest | frontend packages |
| Docker | latest | local postgres + azurite |
| Azure CLI | latest | `az login` for managed-identity dev |

```bash
brew install uv node pnpm docker azure-cli
```

Your Azure Foundry `gpt-image-2` deployment already exists — reuse the endpoint and key
from `../gpt-image-2/.env` for local development.

---

## Starting a session

```bash
cd "/Users/rahulmittal/Main/RnD/AI/Image Generation/emulsion"
claude
```

Then, to begin the next module:

```
/next-module
```

That reads M0, checks which module is next, reads the previous module's open items, and
starts the brainstorming flow for it.

---

## The build order

Modules are finished one at a time, in order. Each is brainstorm → spec → plan → implement →
verify before the next one starts.

| # | Module | What it delivers |
|---|---|---|
| **M0** ✅ | Foundations | Stack, async execution model, Azure topology, portability protocols |
| **M1** | Provider layer | OpenAI/Azure adapters, managed-identity + BYOK auth, retry, cost accounting |
| **M2** | Engine | Prompt compiler, param resolver, candidate generation and ranking — **the moat** |
| **M3** | App shell | Auth, workspaces, sessions, blob storage, image library |
| **M4** | Generation flow | Chat UI, job progress, history, reruns |
| **M5** | Edit subsystem | Conversational edit, attach-and-edit, region crop-composite |
| **M6** | Post-processing | Upscale, transparency, export formats, vector text layer |
| **M7** | Intelligence | Learned constraints, house styles, deck consistency |
| **M8** | Plans & billing | BYOK vs hosted routing, quotas, metering, Stripe |

---

## Provider findings and remaining work

August 12 and 16 probes established that `input_fidelity` and `seed` are rejected, masks
are only soft hints, and the v1 endpoint must omit `api-version`. The capability manifest
records evidence and confidence. Token usage was measured; dollar pricing remains inferred.

M1 still needs its module specification, managed identity, and BYOK. The complete app
pipeline also needs a real-model smoke run. Azure provisioning remains under the user's
control; local feature development and offline checks need none of it.

---

## Slash commands

| Command | Does |
|---|---|
| `/next-module` | Figures out the next module and starts its brainstorm → spec flow |
| `/probe-foundry` | Runs live capability probes against the Foundry deployment |
| `/check-invariants` | Reviews the working tree against M0's architecture non-negotiables |

## Subagents

| Agent | Use for |
|---|---|
| `spec-guardian` | Reviewing a diff against M0's invariants before commit |
| `provider-prober` | Empirically establishing model capabilities against a live endpoint |

---

## The invariants worth remembering as a human

If a review ever surfaces one of these, it's not nitpicking — each one is a rewrite if it
lands:

1. **Every model call is an async job.** No synchronous endpoint ever calls a model.
2. **`engine` / `imaging` / `providers` import nothing web.** They're libraries with a CLI.
3. **No `if model == "..."`.** Models declare capability manifests; the engine reads data.
4. **Image bytes never pass through Python.** Signed URLs only.
5. **Pixels outside an edited region are byte-identical.** This is the product promise.
6. **BYOK keys are write-only.** Never returned, never logged, never in an error.

---

## Reference material

`../gpt-image-2/` — the CLI this grew out of. Reference, not a dependency.

- `generate.py` — three months of Azure Foundry quirks encoded in working code
- `Prompts/` — real structured diagram prompts; the raw material for M2's prompt compiler
- `out/` — real 4K outputs, useful as test fixtures for `imaging`

---

## Still open

- **Logo.** Emulsion's mark: stacked translucent layers with film-edge sprocket notches.
- **Domain.** `emulsion.app` / `useemulsion.com` — check availability.
