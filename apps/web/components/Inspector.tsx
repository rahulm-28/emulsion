"use client";

import { Download, Layers, Pencil, X } from "lucide-react";
import { useEffect, useState } from "react";
import { getLineage, type ImageOut, type JobOut, type ModelOut } from "@/lib/api";
import { formatBytes, formatCost, formatDuration } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  image: ImageOut | null;
  job: JobOut | null;
  model: ModelOut | null;
  open: boolean;
  onClose: () => void;
  onSelect: (image: ImageOut) => void;
  onEdit: (image: ImageOut) => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-[10px] font-medium uppercase tracking-[0.13em] text-subtle-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/60 py-1.5 last:border-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="truncate text-right font-mono text-[11px] text-foreground">
        {value}
      </dd>
    </div>
  );
}

export function Inspector({ image, job, model, open, onClose, onSelect, onEdit }: Props) {
  const [lineage, setLineage] = useState<ImageOut[]>([]);

  useEffect(() => {
    if (!image) {
      setLineage([]);
      return;
    }
    let live = true;
    getLineage(image.id)
      .then((chain) => live && setLineage(chain))
      .catch(() => live && setLineage([]));
    return () => {
      live = false;
    };
  }, [image]);

  if (!open) return null;

  return (
    <aside
      aria-label="Image inspector"
      className="flex w-full shrink-0 flex-col border-l border-border bg-background-subtle lg:w-[322px]"
    >
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
        <h2 className="text-[13px] font-medium text-foreground">Inspector</h2>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close inspector">
          <X />
        </Button>
      </header>

      {!image ? (
        <p className="px-6 py-10 text-center text-xs leading-relaxed text-subtle-foreground">
          Select an image to see how it was made.
        </p>
      ) : (
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          <div className="overflow-hidden rounded-xl border border-border bg-card">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={image.viewer_url}
              alt={image.prompt}
              className="w-full"
              style={{ aspectRatio: `${image.width} / ${image.height}` }}
            />
          </div>

          <div className="flex gap-2">
            <Button asChild variant="secondary" className="flex-1">
              <a href={image.url} download>
                <Download />
                Download
              </a>
            </Button>
            <Button variant="secondary" className="flex-1" onClick={() => onEdit(image)}>
              <Pencil />
              Edit
            </Button>
          </div>

          <Section title="Output">
            <dl>
              <Row label="Dimensions" value={`${image.width}×${image.height}`} />
              <Row label="File size" value={formatBytes(image.size_bytes)} />
              <Row label="Model" value={image.model_id} />
              {job && <Row label="Preset" value={job.size} />}
            </dl>
          </Section>

          {job && (
            <Section title="Accounting">
              <dl>
                <Row label="Tokens in" value={job.input_tokens?.toLocaleString() ?? "—"} />
                <Row
                  label="Tokens out"
                  value={job.output_tokens?.toLocaleString() ?? "—"}
                />
                <Row label="Cost" value={formatCost(job.cost_usd)} />
                <Row
                  label="Duration"
                  value={formatDuration(job.started_at, job.finished_at)}
                />
              </dl>
            </Section>
          )}

          {job && job.events.length > 0 && (
            <Section title="Trace">
              <ol className="space-y-1 rounded-xl border border-border bg-card p-2.5">
                {job.events.map((event) => (
                  <li key={event.seq} className="flex gap-2 font-mono text-[10px]">
                    <span
                      className={cn(
                        "shrink-0",
                        event.kind === "warning"
                          ? "text-accent"
                          : event.kind === "error"
                            ? "text-danger"
                            : "text-subtle-foreground",
                      )}
                    >
                      {event.kind}
                    </span>
                    <span className="min-w-0 flex-1 text-muted-foreground">
                      {event.message}
                    </span>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {lineage.length > 1 && (
            <Section title={`Lineage · ${lineage.length} versions`}>
              <div className="flex gap-1.5 overflow-x-auto pb-1">
                {lineage.map((version, index) => (
                  <button
                    key={version.id}
                    type="button"
                    onClick={() => onSelect(version)}
                    aria-label={`Version ${index + 1}`}
                    aria-current={version.id === image.id ? "true" : undefined}
                    className={cn(
                      "relative shrink-0 cursor-pointer overflow-hidden rounded-lg border transition-colors duration-200",
                      version.id === image.id
                        ? "border-accent-fill"
                        : "border-border hover:border-border-strong",
                    )}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={version.gallery_url}
                      alt=""
                      loading="lazy"
                      className="size-14 object-cover"
                    />
                    <span className="absolute bottom-0 right-0 bg-background/85 px-1 font-mono text-[9px] text-muted-foreground backdrop-blur">
                      v{index + 1}
                    </span>
                  </button>
                ))}
              </div>
              <p className="mt-1.5 flex items-center gap-1 text-[10px] text-subtle-foreground">
                <Layers className="size-3" />
                Every version is retained
              </p>
            </Section>
          )}

          {model && (
            <Section title="Model capabilities">
              <dl>
                <Row label="Provider" value={model.provider} />
                <Row label="Mask support" value={model.mask_support} />
                <Row
                  label="Edits regenerate all"
                  value={model.edit_full_regen ? "yes" : "no"}
                />
                <Row label="Max per request" value={model.max_n_per_request} />
                <Row label="Rate" value={`~${model.approx_rpm}/min`} />
                {model.unsupported_params.length > 0 && (
                  <Row label="Unsupported" value={model.unsupported_params.join(", ")} />
                )}
              </dl>
            </Section>
          )}
        </div>
      )}
    </aside>
  );
}
