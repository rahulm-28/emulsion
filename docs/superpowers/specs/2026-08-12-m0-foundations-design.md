# Emulsion — M0 · Foundations

**Date:** 2026-08-12
**Status:** Approved
**Module:** M0 of 8

---

## 1. Product

Emulsion is an **image generation studio**. Prompt in, or attach images to edit, get a result.
Accounts, persistent sessions, image library and version lineage, download anytime.
Subscription plans or bring-your-own-key. Multiple models.

**The moat is the layer between the user and the model.** Not the model, not the UI — the
middleware that transforms what the user typed into what the model receives, and what the
model returned into what the user sees.

In film, the emulsion is the coated layer where light becomes an image. Same lens, same
light, different emulsion, different picture. Same thesis: same model, better layer,
better output.

### 1.1 What lives in that layer

| Stage | Responsibility | Prior art in `gpt-image-2` CLI |
|---|---|---|
| Prompt compiler | Short user intent → the long, structured, constraint-heavy prompt that actually works | Hand-written in `Prompts/*.md` |
| Param resolver | Size/aspect/pixel-budget validation, quality, format, api-version quirks | `generate.py` size validation |
| Reliability | 429 backoff, 5xx retry, long timeouts | `generate.py` retry wrapper |
| Candidate generation + ranking | Generate K, score, surface the best — not one roll of the dice | none |
| Edit routing | Whole-image vs. region crop-composite, per request | none (always whole-image) |
| Post-processing | Composite, upscale, transparency, export formats | none |
| Learned constraints | Per-workspace rules injected automatically | in the user's head |

### 1.2 Module map

| # | Module | Depends on |
|---|---|---|
| **M0** | Foundations — stack, execution model, deploy, config | — |
| **M1** | Provider layer — adapters, auth modes, retry, cost accounting | M0 |
| **M2** | Engine — prompt compiler, param resolver, candidate ranking *(the moat)* | M1 |
| **M3** | App shell — auth, workspaces, sessions, storage, library | M0 |
| **M4** | Generation flow — chat UI, job progress, history, reruns | M2, M3 |
| **M5** | Edit subsystem — conversational, attach-and-edit, region crop-composite | M2, M4 |
| **M6** | Post-processing — upscale, transparency, export, vector text layer | M2 |
| **M7** | Intelligence — learned constraints, house styles, deck consistency | M4, M5 |
| **M8** | Plans & billing — BYOK vs hosted routing, quotas, metering, Stripe | M1, M3 |

---

## 2. Forced constraint: asynchronous execution

4K generations take **40–300 seconds**. Candidate ranking (M2) multiplies that by K.
Every serverless HTTP timeout ceiling (10–60s) is below this.

**Request/response is therefore impossible.** The shape is fixed from commit one:

```
client → POST /jobs → job_id (immediate)
           ↓
        queue
           ↓
      worker (no timeout ceiling)
           ↓
   SSE progress → result
```

This is not a scaling optimisation deferred to later. Retrofitting async means rewriting
every route, the client, and the data model. It is also what makes M2's K-candidate
generation and M7's deck mode possible at all.

**Consequence:** the worker cannot run on serverless functions. It needs a container.

---

## 3. Topology

```
                        Front Door
                       /          \
                /  →  Next.js      /api/*  →  FastAPI (Container Apps)
                                              ↓
                                     PostgreSQL Flexible Server
                                              ↓
                                     Storage Queue  →  Container Apps Job (worker)
                                              ↓
                              Blob Storage (Hot derivatives / Cool originals)
```

Front Door path-routing means one origin from the browser's perspective: **no CORS, no
split-cookie problems**, and derivative images are edge-cached on the way out.

### 3.1 Service map

| Concern | Azure | Portable swap |
|---|---|---|
| Frontend | Container Apps (Next.js needs SSR → container, not Static Web Apps) | Vercel, any container host |
| API | Container Apps | any container host |
| Worker | **Container Apps Jobs**, event-driven | any container + queue consumer |
| Database | PostgreSQL Flexible Server | any Postgres |
| Blobs | Blob Storage (Hot + Cool) | S3 / R2 |
| Job trigger | Storage Queue | Postgres `SKIP LOCKED`, SQS |
| Secrets | Key Vault | any secret manager |
| Models | AI Foundry — `gpt-image-2` | OpenAI direct |
| Auth | Entra External ID | Clerk / Auth0 / Supabase |
| Edge | Front Door | any CDN |
| Telemetry | Application Insights | OTel → anywhere |

### 3.2 Worker: Container Apps **Jobs**, not a long-running app

Microsoft's guidance splits these: continuously-polling workers should be apps, but jobs
are right when *"each event requires a new instance of the container with dedicated
resources or needs to run for a long time."*

That is this workload exactly — 40–300s per execution, OpenCV operating on 3840×2160
buffers, one correction per execution, fully isolated.

Economics decide it: always-on replicas mean paying for idle. Event-driven jobs spin up,
execute, terminate — **you pay only for actual compute time**, which for bursty early
traffic is the difference between a hobby bill and a real one.

Confirmed limits: `replicaTimeout` defaults to **30 minutes**, maximum **24 hours**.
Worst case here is ~300s × K, comfortably inside the default.

> `ponytail:` per-execution container start adds a few seconds — irrelevant against a
> 40–300s job. If it ever becomes felt latency, switch to a min-replica-1 Container App
> with KEDA queue scaling. Same image, config change only.

---

## 4. Multi-model architecture

**v1 ships with `gpt-image-2` selected and nothing else in the dropdown.** Nothing in this
section adds features now — it is interface shape only. It makes Gemini a weekend instead
of a refactor.

### 4.1 The trap

The obvious abstraction — `ImageProvider.generate()` / `.edit()` — is wrong. It forces
every model to the **lowest common denominator**, discarding exactly the model-specific
knowledge that is the moat. A generic interface actively prevents encoding that
`gpt-image-2` wants a long, zone-structured, constraint-heavy prompt.

### 4.2 Capability manifests

Every model registers a declared manifest — **data, not code**:

```yaml
gpt-image-2:
  provider: azure-foundry | openai
  modalities_in:  [text, image]
  modalities_out: [image]
  pixels:         {min: 655360, max: 8294400, long_edge: 3840, aspect: [0.33, 3.0]}
  mask_support:   soft            # hint, not constraint
  transparency:   false           # M6 post-processes instead
  multi_reference: 16
  input_fidelity: unverified      # M1 pins this down
  edit_mode:      endpoint
  strengths:      {text_rendering: high, structure: high, seam_blend: low}
  prompt_profile: long_structured
  cost_model:     {...}
```

The engine reads manifests. It never contains `if model == "gpt-image-2"`. Adding a model
is a YAML file plus an adapter — and for OpenAI-API-compatible providers, just the YAML.

The registry is **data seeded in the DB**, so a new model is a row plus a config deploy,
not a release.

### 4.3 What manifests buy: per-sub-task routing

`strengths` is routing input, not documentation. Autoregressive models render text well
and blend seams badly; diffusion models are the reverse.

| Sub-task | Routed to | Why |
|---|---|---|
| Diagram with dense labels | AR (`gpt-image-2`) | text fidelity |
| Region fill on flat background | diffusion (Flux) | true masks, clean seams |
| Conversational multi-turn refinement | Gemini | native to its edit model |

The user picks a model or leaves it on **Auto**. Auto is the product. It is only possible
if capabilities are declared data.

### 4.4 Prompt profiles are per-model

A structured zone-spec makes `gpt-image-2` excellent and would make a tag-conditioned
diffusion model worse. The compiler (M2) therefore targets a `prompt_profile` —
`long_structured`, `tag_dense`, `conversational` — not a model. Profiles are shared across
models that behave alike, so N models ≠ N compilers.

### 4.5 Multimodal request shape

Requests carry a **list of typed parts**, never a prompt string:

```python
Request(parts=[
    TextPart("..."),
    ImagePart(role="reference", blob_id=...),
    ImagePart(role="source",    blob_id=...),
    MaskPart(...),
    RegionPart(bbox=...),
])
```

Adapters drop parts their manifest doesn't support and **report what was dropped —
surfaced to the user, never silent**. This makes audio/video/3D outputs later an additive
change rather than a rewrite.

### 4.6 Consequences elsewhere

- **Lineage records the model.** Every version stores model + params + manifest version.
  "Regenerate v3 with Gemini instead" is a first-class action; cross-model lineage is a
  novel feature.
- **BYOK is keyed `(user, provider)`.** The model picker shows only models the user has
  credentials for — hosted-tier models plus whatever their keys unlock.

---

## 5. Repo layout

```
apps/web              Next.js
services/api          FastAPI — routes, auth, thin
services/worker       worker entrypoint
packages/engine       ← M2. the moat. pure Python.
packages/imaging      ← M5/M6 primitives. numpy / OpenCV / Pillow.
packages/providers    ← M1. adapters + retry + cost accounting.
packages/db           models, migrations
infra/                bicep / terraform
```

**Rule: `engine`, `imaging`, and `providers` import nothing web-related.** Not FastAPI, not
the ORM session, not request context. They are libraries with a CLI on top.

This is structural, not stylistic. It means the moat is testable headless from a terminal
while app scaffolding is still being built — and the `gpt-image-2` project's `generate.py`
evolves into that CLI rather than being discarded.

---

## 6. Storage and performance

Real outputs from the prior project run **1.4–13.4 MB each**, and lineage means every
version is retained.

1. **Never proxy image bytes through the API.** Signed URLs; the client fetches blob
   storage directly. Proxying 12 MB through a Python process is how the API falls over.
2. **Derivative pyramid, written at upload time:** archival PNG (original, never mutated)
   + ~2048px WebP (viewer) + ~512px WebP (gallery). A gallery shipping 12 MB PNGs is not a
   slow product, it is a broken one. This is the largest single perceived-performance
   decision in the build.
3. **Diff overlays and region previews compute on the 2048px derivative.** Only the final
   composite touches full resolution.
4. **Tiering:** originals → **Cool** (rarely re-read, cheap to store); derivatives → **Hot**
   behind Front Door cache. Lifecycle policy moves originals Hot → Cool after 30 days.
5. **SSE for job progress**, polling as fallback.
6. **Idempotency keys on job creation.** With a paid hosted tier, a double-submitted retry
   is a double charge.

> `ponytail:` Azure blob egress is not free the way R2's is. Front Door caching means
> derivatives mostly miss origin and originals are rare, so this holds for a long time. If
> egress dominates the bill, move derivatives to a zero-egress store behind the same
> `BlobStore` protocol.

---

## 7. Identity and secrets

### 7.1 Keyless by default

Microsoft recommends Entra ID over API keys, and here it removes nearly every secret:

- Worker → Foundry: `DefaultAzureCredential` + `get_bearer_token_provider`,
  scope `https://cognitiveservices.azure.com/.default`, role **Cognitive Services OpenAI User**
- API → Key Vault, API → Postgres (Entra auth), API → Blob (user-delegation SAS)

**The only long-lived secrets in the system are users' BYOK keys.** The platform key for
the hosted tier ceases to exist.

### 7.2 Two separate credential paths

| | Platform (hosted tier) | User (BYOK) |
|---|---|---|
| Storage | Managed identity — no secret exists | Envelope-encrypted in Postgres, per-user DEK |
| Returned to client | n/a | **Never** — write-only, display last 4 chars |
| Logging | n/a | Redacted at the logger, not the call site |
| Rotation | Ops action | User action |

Write-only key handling from day one. Retrofitting it means a disclosure incident first.

---

## 8. Portability

Exactly three protocols. Azure implementations first.

```python
BlobStore     put / get / signed_url / delete
Queue         enqueue / dequeue / ack
SecretStore   get / put / delete
```

Plus a thin `IdentityProvider` seam at the app edge.

That is the entire portability surface, because everything else is Postgres, containers,
and HTTP — which run unchanged anywhere. **Resist adding more.** A generic cloud
abstraction layer is the most reliable way to make a codebase worse.

Explicitly avoided for lock-in reasons: Durable Functions, Cosmos-specific features,
Event Grid as core plumbing.

---

## 9. Local development

```
docker compose:
  postgres   · same major version as Flexible Server
  azurite    · emulates Blob AND Queue — same code path as prod
  api        · FastAPI, hot reload
  worker     · same image, loop mode instead of job mode
  web        · next dev
```

Azurite matters: blob *and* queue emulation means local dev exercises the real `BlobStore`
and `Queue` implementations rather than stubs. The only non-local dependency is Foundry
itself, pointed at the real deployment.

---

## 10. Testing

- **`imaging`**: fixture images + golden-image comparison. One assertion runs on *every*
  composite — **pixels outside the padded rect are byte-identical to the parent**. That
  invariant is the product promise; it gets a test, not a comment.
- **`engine`**: pure unit tests, no network.
- **`providers`**: recorded/replayed HTTP.
- **One real end-to-end smoke test** against a live key, gated behind an env var so CI does
  not burn money.

---

## 11. Scaling path, ceilings named

| Now | Ceiling | Then |
|---|---|---|
| Event-driven Container Apps Job | per-execution start becomes felt latency | min-replica-1 Container App + KEDA, same image |
| Storage Queue trigger | need ordering/dedup guarantees it lacks | Service Bus behind the same `Queue` protocol |
| Single region | non-local latency complaints | regional workers, replicated blobs |
| Blob egress via Front Door | egress dominates the bill | derivatives to zero-egress store |

---

## 12. Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Wedge | Correction loop for technical diagrams, inside a general studio | Proven personal workflow; nobody sells it |
| Edit mechanism | Crop → edit → align → composite | Drift is architectural in AR models, not a missing parameter |
| Interaction | Language in → proposed region shown → confirm → run | Field is moving to "design software, not slot machine" |
| v1 image scope | Any diagram image in, not only self-generated | Competitors' output becomes input |
| Surface | Hosted web app, BYOK from day one | User decision |
| Providers at launch | OpenAI + Azure OpenAI only | One adapter, two deploy targets, already in production |
| Money at launch | BYOK free + hosted paid tier | User decision |
| Frontend / backend | Next.js / Python | User decision |
| Cloud | Azure-native, portable via 3 protocols | User's own subscription and Foundry deployment |
| Multi-model | Capability manifests from day one, one model in v1 | Interface shape now, features later |

---

## 13. Research basis

- **`gpt-image-2` is autoregressive, not diffusion.** Explains its strength on in-image text,
  layout compliance, and long constraint-heavy prompts — and why partial edits cannot exist.
- **The `mask` parameter is a soft hint, not a hard constraint** for `gpt-image-*` (unlike
  DALL·E-2's true pixel replacement). Masked edits routinely alter regions outside the mask.
- **"The entire image must be regenerated as a new output with gpt-image models. You cannot
  have perfect preservation."** — OpenAI developer community.
- **NEP (NeurIPS 2025)**: AR editors regenerate the whole target and are biased toward
  reconstructing non-edit regions, which degrades the intended edit.
- **SeamEdit (arXiv 2606.13041)**: black-box crop → pad → edit → Grid-SIFT realign → colour
  normalise → rank → DP curved-seam fusion. The reference pipeline for M5.
- **Domain advantage**: flat diagrams with whitespace gutters between zones make seam
  blending near-free compared to photographs — SeamEdit's hardest stage largely evaporates.

### Sources

- https://developers.openai.com/api/reference/python/resources/images/methods/edit
- https://community.openai.com/t/gpt-image-api-how-can-i-reliably-edit-only-the-masked-selected-area-while-preserving-everything-else/1389833
- https://community.openai.com/t/image-editing-inpainting-with-a-mask-for-gpt-image-1-replaces-the-entire-image/1244275
- https://arxiv.org/html/2606.13041 (SeamEdit)
- https://arxiv.org/html/2508.06044 (NEP)
- https://arxiv.org/html/2410.22370v1 (Survey of UI design in generative AI)
- https://learn.microsoft.com/en-us/azure/container-apps/jobs
- https://learn.microsoft.com/en-us/azure/container-apps/scale-app
- https://learn.microsoft.com/en-us/azure/architecture/best-practices/background-jobs
- https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/managed-identity
- https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/configure-entra-id
- https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/dall-e

---

## 14. Open items for M1

- Verify whether `input_fidelity` is accepted on the Foundry `gpt-image-2` edits deployment,
  and whether prior rejection was the model or the `api-version`.
- Verify whether `mask` is accepted at all on the same deployment.
- Pin the generations vs. edits `api-version` divergence (`2024-02-01` returns 404 on edits;
  `2025-04-01-preview` works).
- Establish real cost-per-image at 4K to seed the `cost_model` field.
