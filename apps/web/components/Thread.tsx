"use client";

import {
  AlertTriangle,
  Check,
  Loader2,
  Maximize2,
  Pencil,
  RotateCw,
  Sparkles,
  ImagePlus,
  GitBranch,
} from "lucide-react";
import type { ImageOut, JobOut } from "@/lib/api";
import { formatCost, formatDuration } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type StageState = "pending" | "active" | "done" | "failed";

interface Stage {
  key: string;
  label: string;
  detail: string;
  state: StageState;
}

/**
 * The pipeline, derived from the job's real event trail — not a decorative progress
 * bar. Each stage is backed by an event the worker actually emitted.
 */
export function deriveStages(job: JobOut): Stage[] {
  const messages = job.events.map((e) => e.message);
  const resolved = messages.find((m) => m.startsWith("resolved "));
  const rendering = messages.filter((m) => m.startsWith("rendering candidate")).at(-1);
  const throttled = messages.find((m) => m.includes("rate limit"));
  const failed = job.status === "failed";
  const done = job.status === "succeeded";
  const started = job.status !== "queued";

  if (job.kind === "upload") {
    return [{
      key: "import",
      label: done ? "Image ready" : failed ? "Could not import image" : "Preparing image",
      detail: done ? "Saved to this conversation" : messages.at(-1) ?? "Checking the file and creating previews",
      state: failed ? "failed" : done ? "done" : "active",
    }];
  }

  const state = (reached: boolean, next: boolean): StageState => {
    if (failed && !reached) return "failed";
    if (reached) return "done";
    return next ? "active" : "pending";
  };

  return [
    {
      key: "queued",
      label: "Queued",
      detail: "accepted — no model called yet",
      state: started ? "done" : "active",
    },
    {
      key: "resolve",
      label: "Parameters resolved",
      detail: resolved ?? "validating size against the model manifest",
      state: state(Boolean(resolved), started),
    },
    {
      key: "generate",
      label: "Generating",
      detail: throttled ?? rendering ?? `${job.n} candidate${job.n > 1 ? "s" : ""}`,
      state: state(done || job.images.length > 0, Boolean(resolved)),
    },
    {
      key: "store",
      label: "Stored",
      detail: done
        ? `${job.images.length} image${job.images.length === 1 ? "" : "s"} · ${formatDuration(job.started_at, job.finished_at)}`
        : "writing to blob storage",
      state: failed ? "failed" : done ? "done" : "pending",
    },
  ];
}

function Pipeline({ job }: { job: JobOut }) {
  const stages = deriveStages(job);
  return (
    <ol
      className="w-fit min-w-[16rem] space-y-3 rounded-xl border border-border bg-card p-3.5"
      aria-label={job.kind === "upload" ? "Image preparation" : "Generation pipeline"}
      aria-live="polite"
    >
      {stages.map((stage, index) => (
        <li key={stage.key} className="relative flex items-start gap-2.5">
          {index < stages.length - 1 && (
            <span
              aria-hidden
              className="absolute left-[7px] top-5 h-[calc(100%+2px)] w-px bg-border"
            />
          )}
          <span className="relative z-[1] mt-0.5 grid size-4 shrink-0 place-items-center rounded-full bg-card">
            {stage.state === "done" && <Check className="size-3.5 text-success" />}
            {stage.state === "active" && (
              <Loader2 className="size-3.5 animate-spin text-accent" />
            )}
            {stage.state === "failed" && (
              <AlertTriangle className="size-3.5 text-danger" />
            )}
            {stage.state === "pending" && (
              <span className="size-1.5 rounded-full bg-border-strong" />
            )}
          </span>
          <span className="min-w-0">
            <span
              className={cn(
                "block text-xs leading-tight",
                stage.state === "pending"
                  ? "text-subtle-foreground"
                  : "text-foreground",
              )}
            >
              {stage.label}
            </span>
            <span className="mt-0.5 block font-mono text-[10px] text-subtle-foreground">
              {stage.detail}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function Placeholder({ size }: { size: string }) {
  const aspect =
    size === "4k-uhd" ? "16 / 9" : size === "4k-portrait" ? "9 / 16" : "1 / 1";
  return (
    <div
      className="developing w-full max-w-[18rem] rounded-xl border border-border"
      style={{ aspectRatio: aspect }}
      role="status"
      aria-label="Generating image"
    />
  );
}

function Notice({
  tone,
  children,
}: {
  tone: "warn" | "error";
  children: React.ReactNode;
}) {
  return (
    <p
      className={cn(
        "flex items-start gap-2 rounded-xl border p-3 text-xs leading-relaxed",
        tone === "error"
          ? "border-danger/35 bg-danger/[0.07] text-danger"
          : "border-accent-fill/35 bg-accent-wash text-accent",
      )}
    >
      <AlertTriangle className="mt-px size-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

interface Props {
  jobs: JobOut[];
  selectedImageId: string | null;
  onSelectImage: (image: ImageOut) => void;
  onEdit: (image: ImageOut) => void;
  onRerun: (job: JobOut) => void;
  onUseDiagram: (job: JobOut) => void;
}

export function Thread({ jobs, selectedImageId, onSelectImage, onEdit, onRerun, onUseDiagram }: Props) {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-9 px-4 py-8">
      {jobs.map((job) => (
        <article key={job.id} className="rise space-y-3.5">
          <div className="flex justify-end">
            <p className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-background-subtle px-4 py-2.5 text-[15px] leading-relaxed text-foreground">
              {job.prompt}
            </p>
          </div>

          <div className="flex gap-3">
            <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg border border-border bg-card text-accent-fill">
              {job.kind === "upload" ? <ImagePlus className="size-3.5" /> : <Sparkles className="size-3.5" />}
            </span>

            <div className="min-w-0 flex-1 space-y-3">
              {job.parent_image_id && <p className="text-xs text-muted-foreground">Editing an earlier image{job.region ? " · selected area" : ""}</p>}
              {job.diagram && <Button variant="ghost" size="sm" onClick={() => onUseDiagram(job)} className="max-w-full">
                <GitBranch /><span className="truncate">Use structure · {job.diagram.title}</span>
              </Button>}
              {job.status !== "succeeded" && <Pipeline job={job} />}
              {job.status === "running" && job.kind !== "upload" && <Placeholder size={job.size} />}

              {job.kind === "upload" && job.status === "succeeded" && (
                <p className="text-xs text-muted-foreground">Uploaded image · ready to edit</p>
              )}

              {job.events.filter((event) => event.kind === "warning").map((event) => (
                <Notice key={event.seq} tone="warn">{event.message}</Notice>
              ))}

              {job.error && <Notice tone="error">{job.error}</Notice>}

              {job.dropped_parts.map((dropped) => (
                <Notice key={dropped.kind + dropped.reason} tone="warn">
                  <strong className="font-medium">Dropped {dropped.kind}.</strong>{" "}
                  {dropped.reason}
                </Notice>
              ))}

              {job.images.length > 0 && (
                <div
                  className={cn(
                    "grid gap-2",
                    job.images.length > 1
                      ? "max-w-lg grid-cols-2"
                      : "max-w-[18rem] grid-cols-1",
                  )}
                >
                  {job.images.map((image, index) => (
                    <div key={image.id} className="group relative">
                      <button
                        type="button"
                        onClick={() => onSelectImage(image)}
                        aria-label={job.kind === "upload" ? "Select uploaded image" : `Select candidate ${index + 1}`}
                        className={cn(
                          "block w-full cursor-pointer overflow-hidden rounded-xl border transition-colors duration-200",
                          image.id === selectedImageId
                            ? "border-accent-fill"
                            : "border-border hover:border-border-strong",
                        )}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={image.viewer_url}
                          alt={image.prompt || "Uploaded source image"}
                          loading="lazy"
                          className="w-full object-cover"
                          style={{ aspectRatio: `${image.width} / ${image.height}` }}
                        />
                      </button>

                      {/* Hover actions use opacity, never scale — a transform here
                          would shift the grid under the cursor. */}
                      <div className="absolute right-1.5 top-1.5 flex gap-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100">
                        <Dialog>
                          <Tooltip label="View full size">
                            <DialogTrigger asChild>
                              <Button
                                variant="secondary"
                                size="icon-sm"
                                aria-label="View full size"
                                className="bg-card/90 backdrop-blur"
                              >
                                <Maximize2 />
                              </Button>
                            </DialogTrigger>
                          </Tooltip>
                          <DialogContent>
                            <DialogTitle className="sr-only">{image.prompt}</DialogTitle>
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={image.url}
                              alt={image.prompt}
                              className="max-h-[86vh] w-full rounded-xl object-contain"
                            />
                          </DialogContent>
                        </Dialog>

                        <Tooltip label="Edit this image">
                          <Button
                            variant="secondary"
                            size="icon-sm"
                            onClick={() => onEdit(image)}
                            aria-label="Edit this image"
                            className="bg-card/90 backdrop-blur"
                          >
                            <Pencil />
                          </Button>
                        </Tooltip>
                      </div>

                      {job.images.length > 1 && (
                        <span className="pointer-events-none absolute left-2 top-2 rounded-md bg-background/85 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground backdrop-blur">
                          {index + 1}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {job.status === "succeeded" && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-subtle-foreground">
                  <span>
                    {job.images[0]?.width}×{job.images[0]?.height}
                  </span>
                  <span aria-hidden>·</span>
                  <span>{job.kind === "upload" ? "Imported" : `${job.output_tokens?.toLocaleString()} tok`}</span>
                  <span aria-hidden>·</span>
                  <span>{formatCost(job.cost_usd)}</span>
                  <span aria-hidden>·</span>
                  <span>{formatDuration(job.started_at, job.finished_at)}</span>
                  {job.kind !== "upload" && <button
                    type="button"
                    onClick={() => onRerun(job)}
                    className="-my-2 inline-flex cursor-pointer items-center gap-1 py-2 text-accent underline-offset-2 transition-colors duration-200 hover:underline"
                  >
                    <RotateCw className="size-3" />
                    rerun
                  </button>}
                </div>
              )}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
