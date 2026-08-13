# Emulsion

Image generation studio. Prompt in, or attach images to edit, get a result. Accounts,
persistent sessions, image library with version lineage, download. Subscription plans or
bring-your-own-key. Multiple models.

**The moat is the layer between the user and the model** — the middleware that turns user
intent into the prompt the model actually needs, and raw model output into finished work.
Not the model. Not the UI. In film, the emulsion is the coated layer where light becomes an
image: same lens, same light, different emulsion, different picture.

---

## Read this first

**`docs/superpowers/specs/2026-08-12-m0-foundations-design.md` is the source of truth for
architecture.** This file is a summary and a set of guardrails. When they disagree, the spec
wins — and fix this file.

---

## Current state

A **runnable vertical slice** exists: `make install && make dev`, then localhost:3000.
It runs with no Docker and no cloud account, on an `echo` adapter that generates images
locally for free. `EMULSION_ADAPTER=foundry` switches to the real model.

This slice deliberately reaches ahead of the module order to make the architecture
testable end to end. Everything it contains is either M0-decided or a `ponytail:`-marked
placeholder — **no module is finished**, and each still needs its own spec.

| Module | Status |
|---|---|
| **M0** Foundations — stack, execution model, deploy, config | ✅ spec approved |
| **M1** Provider layer — adapters, auth modes, retry, cost accounting | 🟨 manifests, sizing, cost, throttle, echo + foundry adapters built; **no spec, no managed identity, no BYOK** |
| **M2** Engine — prompt compiler, param resolver, candidate ranking *(the moat)* | 🟨 prompt compiler + constraint packs + spec validation built; ranking primitives built in `imaging`; **no spec, not wired to a UI spec editor** |
| **M3** App shell — auth, workspaces, sessions, storage, library | 🟨 identity seam with dev + Clerk providers, per-user ownership on every row and route, isolation tested; **no workspaces, no sign-in UI** |
| **M4** Generation flow — chat UI, job progress, history, reruns | 🟨 conversations, live pipeline, history and reruns work; no streaming partials |
| **M5** Edit subsystem — conversational, attach-and-edit, region crop-composite | 🟨 region crop-composite works end to end — draw an area, edit it, rest of the image stays byte-identical (asserted through the API in a test); **no conversational edit, no mask path** |
| **M6** Post-processing — upscale, transparency, export, vector text layer | 🟨 derivative pyramid, transparency (border-connected flood fill, refuses on non-flat images), PNG/WebP/JPEG export, Lanczos resize; **no model upscale, no vector text** |
| **M7** Intelligence — learned constraints, house styles, deck consistency | 🟨 house styles, opt-in deck consistency, and clause-counted suggestions with visible evidence; **suggestions are never auto-applied**, no cross-user learning |
| **M8** Plans & billing — BYOK vs hosted routing, quotas, metering, Stripe | 🟥 stubbed — `quota.check()` runs on the paid path and always allows; no metering, no Stripe, no BYOK routing |

Modules are completed **one at a time, in order**. Each gets: brainstorm → spec → plan →
implement → verify.

The vertical slice above is scaffolding that cuts across several of them on purpose — it
exists so the invariants are enforced by running code rather than by a document. It does
not make any module done. When you pick up a module, spec it properly and expect to
replace the placeholder rather than extend it.

### Predecessor project

`../gpt-image-2/` is the working CLI this product grew out of. It is **reference, not a
dependency** — read it for hard-won Azure Foundry knowledge (`generate.py` especially), and
for real prompt examples in `Prompts/` and real 4K outputs in `out/`.

---

## Architecture non-negotiables

These are not style preferences. Violating any of them means a rewrite later.

### 1. Everything is an async job

4K generations take **40–300 seconds**; candidate ranking multiplies that by K. Every
serverless HTTP ceiling is below this.

```
client → POST /jobs → job_id (immediate) → queue → worker → SSE progress → result
```

Never add a synchronous endpoint that calls a model. Never.

### 2. `engine`, `imaging`, and `providers` import nothing web

Not FastAPI, not the ORM session, not request context, not settings that assume a request.
They are libraries with a CLI on top. This is what lets the moat be tested headless.

If you find yourself passing a `Request` or a DB session into `packages/engine`, stop — the
boundary is wrong.

### 3. No `if model == "..."` anywhere in the engine

Models declare **capability manifests** (data, seeded in DB). The engine reads manifests.
A generic `ImageProvider.generate()/edit()` interface is explicitly rejected — it forces
every model to the lowest common denominator and destroys the differentiation.

Adding a model = a manifest row + maybe an adapter. Never an `if`.

### 4. Image bytes never pass through Python

Signed URLs; the client fetches blob storage directly. Proxying 12 MB through a FastAPI
worker is how the API falls over.

### 5. The composite invariant

For any region edit: **pixels outside the padded rect are byte-identical to the parent.**
That is the product promise. It is asserted in code on every composite, and it has a test.
It is not a comment.

### 6. BYOK keys are write-only

Never returned to a client, never logged (redact at the logger, not the call site), never
in an error message. Envelope-encrypted at rest, per-user DEK. Display last 4 characters
only.

### 7. Requests carry typed parts, not a prompt string

```python
Request(parts=[TextPart(...), ImagePart(role="source"|"reference", ...), MaskPart(...), RegionPart(...)])
```

Adapters drop parts their manifest doesn't support and **report what they dropped** —
surfaced to the user, never silent.

### 8. Idempotency keys on job creation

A double-submitted retry on a paid tier is a double charge.

---

## Planned repo layout

Directories are created by the module that needs them — do not scaffold empty trees.

```
apps/web              Next.js
services/api          FastAPI — routes, auth, thin
services/worker       worker entrypoint
packages/engine       M2. the moat. pure Python.
packages/imaging      M5/M6 primitives. numpy / OpenCV / Pillow.
packages/providers    M1. adapters + retry + cost accounting.
packages/db           models, migrations
infra/                bicep
docs/superpowers/specs/   design docs, one per module
docs/superpowers/plans/   implementation plans
```

---

## Stack

Decided in M0. Change only with a spec amendment.

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic |
| Package manager | `uv` (workspace mode across `packages/*` and `services/*`) |
| Lint + format | `ruff` (both) |
| Tests | `pytest` |
| Imaging | `numpy`, `opencv-python-headless`, `Pillow` |
| Frontend | Next.js App Router, TypeScript, Tailwind, `pnpm`, Node 22 |
| Database | PostgreSQL 16 |
| Cloud | Azure — Container Apps, Container Apps Jobs, Blob Storage, Storage Queue, Key Vault, Front Door, AI Foundry |
| Local | `docker compose` — postgres + azurite + api + worker + web |

**Portability surface is exactly three protocols** — `BlobStore`, `Queue`, `SecretStore` —
plus a thin `IdentityProvider` seam. Everything else is Postgres, containers, and HTTP,
which run anywhere. Do not build a generic cloud abstraction layer; it is the most reliable
way to make this codebase worse.

Explicitly avoided for lock-in: Durable Functions, Cosmos-specific features, Event Grid as
core plumbing.

---

## Domain knowledge — read before touching provider or engine code

### `gpt-image-2` is autoregressive, not diffusion

It emits visual tokens sequentially. Consequences:

- **Excellent** at in-image text, layout compliance, and long constraint-heavy prompts.
  This is why it beats diffusion models at technical diagrams.
- **Partial edits do not exist.** Every edit call regenerates the entire image. There is no
  parameter that changes this — it is architectural.

### The `mask` parameter is a hint, not a constraint

Unlike DALL·E-2 (true pixel replacement), `gpt-image-*` treats a mask as a soft image
prompt. Masked edits routinely alter regions outside the mask. Do not build anything that
assumes mask = guarantee.

### Therefore: crop → edit → align → composite

The only real answer to drift, per SeamEdit (arXiv 2606.13041):

1. Crop the region **plus context padding**
2. Send only the crop to `/images/edits`, generate K candidates
3. Affine re-align back to reference coords (output comes back shifted and off-tone)
4. Per-channel colour normalise against the **untouched border ring**
5. Rank on seam discontinuity, alignment residual, change-outside-region
6. Feathered alpha composite into a copy of the original at full resolution

**Domain advantage:** flat diagrams have whitespace gutters between zones. Snap crop
boundaries to low-variance rows/columns and there is nothing to blend — SeamEdit's hardest
stage largely evaporates. This is why this product is viable and a photo-editing equivalent
would not be.

### Azure Foundry quirks (from `../gpt-image-2/generate.py`)

Measured against the live deployment on 2026-08-12. The manifest at
`packages/providers/.../manifests/gpt-image-2.yaml` carries per-field provenance; trust it
over this summary.

- **One api-version covers both endpoints:** `2025-04-01-preview` works on
  `/images/generations` *and* `/images/edits`. `2024-02-01` 404s on edits. There is no need
  for the URL-rewrite trick `generate.py` uses.
- **`input_fidelity` is unsupported** — a hard model-level 400, not an api-version artefact
- **`mask` is accepted but does not hold**: 93.5% of pixels outside the mask still moved
  (mean 6.46/255). Full-image regeneration with a soft bias. This is *why* M5 crops and
  composites
- **`n=2` returns 2 images in one request** — one rate-limit slot. Candidate generation is
  far cheaper than K separate calls
- **Rate limit is 2 requests per 11s (~10.9 rpm)**, from `x-ratelimit-*` headers — *not* the
  "2 RPM" claimed in `generate.py:223`
- **Both `api-key:` and `Authorization: Bearer` authenticate**, so hosted and BYOK can share
  one code path
- **Cost scales viciously with size:** 107 / 1413 / 13342 output tokens at 1024x640 low,
  2048x1152 medium, 3840x2160 high. ~**$0.53 per 4K image** — but the USD rate is *inferred*
  from OpenAI's published pricing, not confirmed against an Azure invoice
- Edits require `multipart/form-data`, PNG or JPG input (not HEIC); references go in `image[]`
- Size rules: min 655,360 px · max 8,294,400 px · long edge ≤ 3840 · aspect ≤ 3:1 ·
  **each edge a multiple of 16** · 50 MB per input file
- Retry: 429 → backoff `[5, 15, 45]` but prefer the `Retry-After` header; 5xx → once; timeout 300s
- Transparency is **not supported** — M6 post-processes it instead

**Open, and it decides M2's economics:** is a `seed` parameter accepted, and is it stable
across sizes? If yes, rank K cheap candidates and re-render the winner at 4K (~$0.55/action).
If no, ranking must happen at full resolution (~$2.13/action at K=4).

### Auth: keyless for platform, BYOK for users

Hosted tier uses managed identity — `DefaultAzureCredential` + `get_bearer_token_provider`,
scope `https://cognitiveservices.azure.com/.default`, role **Cognitive Services OpenAI
User**. There is no platform API key. The only long-lived secrets in the system are users'
BYOK keys.

### Cost and size reality

Real 4K outputs run **1.4–13.4 MB each**, and lineage retains every version. Hence:
derivative pyramid on write (archival PNG + ~2048px WebP viewer + ~512px WebP gallery),
originals in Cool tier, derivatives in Hot behind Front Door. Diff overlays and region
previews compute on the 2048px derivative — only the final composite touches 4K.

---

## Workflow

1. **Brainstorm** the module (`superpowers:brainstorming`) — one question at a time
2. **Spec** it to `docs/superpowers/specs/YYYY-MM-DD-<module>-design.md`, commit
3. **Plan** it (`superpowers:writing-plans`) to `docs/superpowers/plans/`, commit
4. **Implement** — TDD where the logic is non-trivial
5. **Verify** before claiming done — run the checks, show the output

Every module's spec ends with an **open items** section that feeds the next module. Read the
previous module's open items before starting.

---

## Conventions

- Type hints everywhere in Python; `ruff` clean before commit
- Non-trivial logic leaves one runnable check behind — an assert-based `demo()` or a small
  `test_*.py`. No frameworks, no fixtures unless asked.
- Deliberate shortcuts with a known ceiling get a `ponytail:` comment naming the ceiling and
  the upgrade path
- Commits are conventional (`feat:`, `fix:`, `docs:`, `refactor:`)
- Never commit `.env`. `.env.example` documents every variable.

## Things that are not up for debate without a spec amendment

Synchronous model calls · a common `ImageProvider` interface · proxying image bytes through
the API · returning a BYOK key to a client · scaffolding empty directories · adding a fourth
portability protocol.
