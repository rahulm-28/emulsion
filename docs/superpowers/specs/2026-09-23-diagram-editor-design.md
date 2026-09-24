# Structured diagrams and editing controls

Extend the existing pure engine spec into a usable product workflow. This is a feature
slice, not completion of all M2 or M5 requirements.

## User workflow

An inline Structure editor occupies the conversation canvas when opened. Users enter a
title, key message, layout, components, connections, and annotations using the existing
theme and Radix controls. Renaming a component updates references; removing one removes
its connections and anchored annotations. Invalid references or duplicate names prevent
submission. The compiled prompt is available as a free deterministic preview.

The structure travels with a generation and can be reopened from its history entry.
An additive `job_specifications` table stores JSON without altering existing tables.
Wire validation lives at the API boundary; the worker converts stored data to the engine's
plain dataclasses. Both free-text and structured requests retain the full user instructions.

## Editing polish

The composer offers Auto, New image, and Edit latest routing. A selected source overrides
Auto; New image explicitly ignores conversational inference. Edit latest with no image is
rejected before queueing. History labels actual edits. Reruns submit the original model,
size, count, parent, region, and diagram rather than reading stale composer state.

The inspector becomes a keyboard-accessible sheet on narrow screens so image export and
lineage remain available. Progress reconnects use a polling fallback, and revisiting an
active conversation resumes progress. First-job style selection is applied before queueing.

## Validation

Bound field lengths and item counts; reject dangling connections, duplicate component
names, and orphan annotations before work is accepted. Verify saved structure reaches the
provider request, user instructions survive compilation, ownership holds on preview/style
selection, routing overrides work, and old SQLite data survives additive initialization.
Run the offline suite, frontend typecheck, and browser checks of editor, preview, generation,
reuse, rerun, and mobile inspector. No paid provider calls or Azure provisioning.

## Delivered and checked

- API and worker: structured persistence, owner-scoped preview, inherited edit structure,
  full written instructions, explicit routing, atomic initial style selection, and UTC
  timestamps on wire responses. Existing SQLite tables are preserved.
- UI: structure editor and validation, history reuse, precise rerun parameters, mobile
  inspector/export, compact mobile composer, hidden mobile navigation excluded from focus,
  and progress recovery after disconnect or conversation navigation.
- Automated: 342 Python tests; five Node tests covering stream replay, connection recovery,
  stale navigation responses, silent connections, and repeated network failures. TypeScript,
  Ruff, formatting, and whitespace checks pass. The Next.js production build passes
  with network access for its existing Google Fonts dependency.
- Browser: built and renamed a two-component diagram, linked and annotated it, previewed
  the full prompt, generated and reopened it from history, edited it, and reran the original
  with different draft settings. At a 375px viewport, verified dark/light rendering,
  mobile inspector and WebP export. Left a running conversation and returned before it
  finished; progress resumed and the result arrived. New dates display under Today.
- All generation checks used the free local echo adapter. Real-provider image quality,
  production deployment, and billing remain outside this feature slice.
