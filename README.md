# Emulsion

> Same model, better layer.

An image generation studio. Prompt in, or attach images to edit, get a result. Accounts,
persistent sessions, image library with version lineage, download anytime. Subscription
plans or bring-your-own-key. Multiple models.

The differentiator is the layer between the user and the model — prompt compilation,
parameter resolution, candidate ranking, edit routing, post-processing, learned constraints.
In film, the emulsion is the coated layer where light becomes an image: same lens, same
light, different emulsion, different picture.

---

## Why this exists

I built this for myself.

I kept needing technical diagrams — architecture diagrams, system layouts, the kind of
thing that goes in a deck or a blog post — and image models are genuinely good at them.
`gpt-image-2` in particular renders in-image text and holds layout constraints far better
than diffusion models do, because it is autoregressive.

What I did not have was a way to *work* with it. Every generation was one roll of the
dice. Fixing one label meant regenerating the whole image and losing everything else that
was already right. The prompts that actually worked were long, structured, and lived in a
folder of markdown files I copy-pasted from. There was no history, no versions, no way to
tell what a run had cost me.

So this is the tooling I wanted: the middleware between a short intent and the long
constraint-heavy prompt the model actually needs, plus the machinery around it — sessions,
version lineage, cost accounting, and a correction loop that edits a region without
disturbing the rest of the picture.

It started as a personal tool and it is still shaped like one. I am putting it out
publicly because the problem is not unique to me — if you generate technical images and
have hit the same walls, take it, run it, change it. It runs entirely on your machine with
no cloud account and no API key (see below), so trying it costs nothing.

**Fair warning on where it actually is:** generation, region editing, sessions, lineage
and cost accounting all work end to end. What is missing is accounts, billing, and the
learned-constraint work — and there is no conversational edit yet, only draw-an-area.
Read [CLAUDE.md](CLAUDE.md) for an honest per-module status before assuming a feature
exists.

---

## Run it

No Docker, no cloud account, no API key. The default adapter is `echo`, which generates
images locally so the whole flow works for free.

```bash
make install        # uv sync + pnpm install
make dev            # API on :8000, web on :3000
```

Open **http://localhost:3000**.

The browser only ever talks to `:3000` — Next rewrites `/v1/*` and `/_blobs/*` to the API,
which is the same single-origin shape Front Door gives in production. No CORS anywhere.

### Talking to the real model

```bash
export AZURE_ENDPOINT=...        # the /images/generations URL
export AZURE_API_KEY=...
export EMULSION_ADAPTER=foundry
make dev
```

Generations cost real money — roughly **$0.53 per 4K image** at current token rates. The
`echo` default exists so nothing reaches a paid endpoint by accident.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `EMULSION_ADAPTER` | `echo` | `echo` (offline, free) or `foundry` (real) |
| `EMULSION_AUTH` | `dev` | `dev` is one implicit local user; `clerk` verifies real session JWTs |
| `EMULSION_DATA_DIR` | `.data` | SQLite file and the local blob store |
| `DATABASE_URL` | SQLite in `EMULSION_DATA_DIR` | Point at Postgres for the production shape |
| `EMULSION_INLINE_WORKER` | `1` | `0` runs the worker as its own process, as production does |
| `EMULSION_ECHO_LATENCY_S` | `0.6` | Fake generation latency, so progress is observable |
| `AZURE_ENDPOINT` / `AZURE_API_KEY` | — | Only needed for `EMULSION_ADAPTER=foundry` |

### The production-shaped stack

```bash
docker compose up -d                                   # postgres + azurite
export DATABASE_URL=postgresql+psycopg://emulsion:emulsion@localhost:5432/emulsion
make api    # in one shell
make worker # in another — EMULSION_INLINE_WORKER=0
make web    # in a third
```

---

## What exists

| Layer | Status |
|---|---|
| `packages/platform` | The three portability protocols + filesystem/env implementations |
| `packages/db` | Jobs, events, images with lineage, queue table |
| `packages/providers` | Manifests, sizing, cost, throttle, `echo` + `foundry` adapters |
| `packages/engine` | **Prompt compiler** — structured diagram spec, constraint packs, spec validation |
| `packages/imaging` | Gutter snapping, alignment, colour matching, seam scoring, composite, derivatives, export |
| identity | `dev` (single local user) or Clerk, behind M0's `IdentityProvider` seam |
| `services/api` | FastAPI: create job, list, SSE progress, library, lineage |
| `services/worker` | Queue consumer, inline or standalone |
| `apps/web` | Next.js studio — conversations, model picker, live pipeline, inspector, lineage |

### The interface

Light and dark, minimal, one warm accent. Instrument Sans for UI, Instrument Serif for
the wordmark and display line, JetBrains Mono for readouts. Radix primitives (Select,
Dropdown, Tooltip, Dialog) — no native form controls.

- **Conversations** in the left rail, grouped by recency, searchable, renameable, with
  a thumbnail and running cost per conversation
- **Composer** with model, size and candidate-count pickers driven by the model's own
  manifest — the count ceiling *is* `n_per_request`, not a guess
- **Pipeline panel** showing each stage as it happens (queued → resolved → generating →
  stored), derived from the job's real event trail rather than a decorative progress bar
- **Inspector** with output facts, token/cost accounting, the full event trace, version
  lineage, and the model's measured capabilities
- **Edit any image** to start a new version; lineage is walkable both ways
- **House styles** — a named legend, extra rules and a layout that every diagram in a
  conversation inherits; anything typed for one diagram still wins
- **Deck consistency**, opt-in per conversation — asks the model to match the previous
  picture, so a set reads as a deck
- **Learned constraints** — clauses you keep typing are surfaced with the prompts that
  produced them, and only apply once you add them to a style
- **Export** as PNG / WebP / JPEG, at 0.5–2×, with the background knocked out for
  slides — and it refuses rather than guessing when the image has no flat background
- **Rerun** any generation with the same parameters and a fresh sample
- **Draw an area to edit just that part** — the region is grown to a size the model
  accepts and snapped onto whitespace, and everything outside it stays byte-identical

Theme is a three-way control (light / system / dark) — "system" is a real preference, and
a two-way flip means the app stops following the OS the first time it's clicked.

Verified at 375px with no horizontal scroll and no undersized touch targets. Contrast
measured in-browser in **both** themes, worst case on `--card`:

| | body | secondary | tertiary | accent | button |
|---|---|---|---|---|---|
| light | 19.0 | 8.4 | 5.0 | 5.4 | 18.4 |
| dark | 17.3 | 7.5 | 5.0 | 9.9 | 18.0 |

All above the 4.5:1 floor. `prefers-reduced-motion` disables the shimmer and every
transition.

`make check` runs ruff, the Python suite, and the frontend typecheck.

---

## Where things are

```
docs/superpowers/specs/    design docs — one per module, the source of truth
docs/superpowers/plans/    implementation plans
CLAUDE.md                  agent instructions + architecture guardrails
INSTRUCTIONS.md            the human-facing guide
```

- **Humans start here:** [INSTRUCTIONS.md](INSTRUCTIONS.md)
- **Agents start here:** [CLAUDE.md](CLAUDE.md)
- **Architecture:** [M0 foundations](docs/superpowers/specs/2026-08-12-m0-foundations-design.md)
