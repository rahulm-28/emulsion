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

**Current scope:** generation, image uploads, conversational and region editing, sessions,
lineage, a structured diagram editor with prompt preview, Clerk accounts, house styles,
constraint suggestions, and cost tracking are built. Billing remains a stub. BYOK,
workspaces, model upscaling,
vector text, and production storage/deployment are still unfinished. Offline checks cover
the full flow; a complete real-model run through the app remains to be verified.
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

If `.env` or `local.mk` already selects Clerk or PostgreSQL, use `make dev-local` for a
free, isolated demo. It uses the echo provider, SQLite, and a separate `.data-local/`
directory, without changing those configuration files. Echo produces test diagrams;
it does not perform a real AI edit.

### Edit an existing image

Click **Attach image**, drop a file onto the composer, or paste an image. PNG, JPEG, and
WebP are supported, up to 50 MB and 32 megapixels. The worker prepares a PNG and previews
without a model call, then saves the image in the conversation. Describe a change and send,
or use **Select area** for a region edit. The source remains in version history.

Photos are oriented correctly and metadata is removed. Transparent areas are placed on
white for the current RGB edit pipeline, with a notice. Region edits may expand your
selection to a size the model accepts; pixels outside that expanded rectangle are preserved.
Whole-image conversational edits regenerate the image and do not provide that guarantee.

Uploads currently use local storage emulation. Direct cloud uploads and abandoned-upload
cleanup are required before production deployment.

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

### Build a structured diagram

Open **Structure** in the composer to define a title, key message, layout, components,
connections, and annotations. Component names stay connected when renamed. **Preview
prompt** shows the compiled instructions without calling a model. Add any final guidance
in the composer, then send; a title alone is enough to submit a valid structure.

Every structured generation keeps its own saved copy. **Use structure** in history opens
that copy for reuse. Follow-up edits inherit it and retain earlier written instructions.
**New image** forces a fresh generation; **Edit latest** uses the latest image in the
conversation; **Auto** keeps conversational routing. Selecting an image explicitly sets
it as the edit source. Rerun uses that job's model, size, count, source, region, and structure.

The inspector supports export and version history on both desktop and mobile. Progress
recovers through polling when the live connection drops; reopening an active conversation
resumes tracking. The echo adapter verifies the workflow, not real-model visual quality.

### Configuration

Copy `.env.example` to `.env` and edit it. The API and worker load the nearest `.env`
at or above the working directory, so it is found whether you run `make dev` from the
repo root or `uvicorn` from inside `services/api`.

`.env.example` documents every variable, including ones whose *example values are not
defaults* — `DATABASE_URL` shows the Postgres form. Copy the file wholesale and the
offline path stops working, because Postgres needs `uv sync --extra postgres` and a
running server. Comment out anything you are not deliberately turning on.

**A real environment variable always beats the file.** Anything already exported — by
`make`, a container, or CI — is a deliberate act, and a file on disk should not
silently override a deploy's own configuration. `local.mk` is exported by `make` and so
outranks `.env`; delete it once `.env` holds the same values, or the stale copy wins
without saying so.

| Variable | Default | Purpose |
|---|---|---|
| `EMULSION_ADAPTER` | `echo` | `echo` (offline, free) or `foundry` (real) |
| `EMULSION_AUTH` | `dev` | `dev` is one implicit local user; `clerk` verifies real session JWTs |
| `CLERK_JWKS_URL` / `CLERK_ISSUER` | — | Only for `EMULSION_AUTH=clerk` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | — | Turns the sign-in UI on; absent means local mode |
| `EMULSION_DATA_DIR` | `.data` | SQLite file and the local blob store |
| `DATABASE_URL` | SQLite in `EMULSION_DATA_DIR` | Point at Postgres for the production shape |
| `EMULSION_INLINE_WORKER` | `1` | `0` runs the worker as its own process, as production does |
| `EMULSION_ECHO_LATENCY_S` | `0.6` | Fake generation latency, so progress is observable |
| `AZURE_ENDPOINT` / `AZURE_API_KEY` | — | Only needed for `EMULSION_ADAPTER=foundry` |

### Turning on accounts

Sign-in is off until it is configured, so the default stays "runs on your machine with
no account". Anyone in the world can sign up once it is on — email and password, or a
social provider.

The web half is one command, which writes `apps/web/.env.local`, `middleware.ts` and the
`/sign-in` + `/sign-up` routes:

```bash
cd apps/web && pnpm dlx clerk@latest auth login
pnpm dlx clerk@latest init
```

The API half is not something the Clerk CLI knows about — it verifies the JWT itself,
against the published JWKS, with no call back to Clerk on the request path. Copy
`.env.example` to `.env` and set three values:

```bash
EMULSION_AUTH=clerk
CLERK_JWKS_URL=https://YOUR-APP.clerk.accounts.dev/.well-known/jwks.json
CLERK_ISSUER=https://YOUR-APP.clerk.accounts.dev
```

Remove them to go back to single-user local mode. Setting it on the web side only is the
one combination to avoid: the browser would send real Clerk tokens while the API still
ran the dev identity, filing everyone's work under `local-user`. Quick check —
`curl -s -o /dev/null -w '%{http_code}' localhost:8000/v1/sessions` must print `401`.

Nothing else changes. Every row already carries an owner and every route already filters
on it — the seam is `packages/platform/identity.py`, and swapping Clerk for anything that
issues a JWT means writing one class.

Clerk session tokens carry no profile fields by default, so the session needs two
claims before `users.email` is anything but blank:

```bash
clerk config patch --json '{"session":{"claims":{
  "email":"{{user.primary_email_address}}","name":"{{user.full_name}}"}}}'
```

The API copies both onto the user row on every request, not just the first, so a claim
added after an account exists still lands on it.

**Set a custom domain before going live.** On the development instance the browser talks
to `YOUR-APP.clerk.accounts.dev`; a CNAME keeps everything on your own origin, which is
one less thing for a user to mistake for a phishing page.

Clerk's own screens follow the app's theme in both light and dark — the palette is
mapped in `components/clerk/ClerkRoot.tsx`, since a white sign-in card on a near-black
page is the first thing a new user would otherwise see.

### The production-shaped stack

```bash
uv sync --extra postgres                               # psycopg is not in the default install
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
