"use client";

import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { exportImage, type ExportOut, type ImageOut } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatBytes } from "@/lib/format";

type Format = "png" | "webp" | "jpeg";

const SCALES = [
  { value: "1", label: "Original" },
  { value: "2", label: "2× larger" },
  { value: "0.5", label: "Half size" },
];

/**
 * Post-processing on the way out: format, transparency, size.
 *
 * Transparency is the one that matters for this product. `gpt-image-2` cannot return
 * an alpha channel at all, so a diagram always arrives on an opaque rectangle — which
 * is wrong the moment it goes on a slide with any background but white.
 */
export function ExportPanel({ image }: { image: ImageOut }) {
  const [format, setFormat] = useState<Format>("png");
  const [scale, setScale] = useState("1");
  const [transparent, setTransparent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ExportOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  // JPEG cannot carry alpha; saying so is better than silently ignoring the checkbox.
  const alphaPossible = format !== "jpeg";

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await exportImage(image.id, {
          format,
          transparent: transparent && alphaPossible,
          scale: Number(scale),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2.5">
      <div className="flex gap-2">
        <Select value={format} onValueChange={(v) => setFormat(v as Format)}>
          <SelectTrigger aria-label="Export format" className="flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>Format</SelectLabel>
              <SelectItem value="png" hint="lossless">
                PNG
              </SelectItem>
              <SelectItem value="webp" hint="smaller">
                WebP
              </SelectItem>
              <SelectItem value="jpeg" hint="no alpha">
                JPEG
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>

        <Select value={scale} onValueChange={setScale}>
          <SelectTrigger aria-label="Export size" className="flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>Size</SelectLabel>
              {SCALES.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      <label
        className={`flex cursor-pointer items-start gap-2 text-[11px] leading-relaxed ${
          alphaPossible ? "text-muted-foreground" : "cursor-not-allowed opacity-50"
        }`}
      >
        <input
          type="checkbox"
          checked={transparent && alphaPossible}
          disabled={!alphaPossible}
          onChange={(e) => setTransparent(e.target.checked)}
          className="mt-0.5 size-3.5 cursor-pointer accent-[var(--accent-fill)]"
        />
        <span>
          Transparent background
          {!alphaPossible && <span className="block text-[10px]">JPEG has no alpha</span>}
        </span>
      </label>

      <Button variant="secondary" className="w-full" onClick={run} disabled={busy}>
        {busy ? <Loader2 className="animate-spin" /> : <Download />}
        {busy ? "Processing…" : "Export"}
      </Button>

      {error && <p className="text-[11px] text-danger">{error}</p>}

      {result && !result.background_uniform && (
        <p className="rounded-lg border border-accent-fill/35 bg-accent-wash p-2.5 text-[11px] leading-relaxed text-accent">
          This image has no single background colour, so transparency was skipped rather
          than applied wrongly — removing &ldquo;the background&rdquo; from a gradient or
          a photo cuts into the subject.
        </p>
      )}

      {result && (
        <a
          href={result.url}
          download
          className="flex items-center justify-between gap-2 rounded-lg border border-accent-fill/45 bg-accent-wash px-3 py-2 text-[11px] text-accent transition-colors duration-200 hover:border-accent-fill"
        >
          <span>
            Download {result.width}×{result.height}
            {result.has_alpha && " · transparent"}
          </span>
          <span className="font-mono">{formatBytes(result.size_bytes)}</span>
        </a>
      )}
    </div>
  );
}
