"use client";

import { ArrowUp, GitBranch, ImagePlus, Layers, Square, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ImageOut, ModelOut, Region } from "@/lib/api";
import { RegionPicker } from "@/components/RegionPicker";
import { StylePanel } from "@/components/StylePanel";
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
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const MAX_COMPOSER_HEIGHT = 320;

const SIZE_HINTS: Record<string, string> = {
  "1k": "1024²",
  "2k": "2048²",
  "4k-uhd": "3840×2160",
  "4k-square": "2880²",
  "4k-portrait": "2160×3840",
};

interface Props {
  prompt: string;
  onPrompt: (value: string) => void;
  models: ModelOut[];
  modelId: string;
  onModel: (id: string) => void;
  size: string;
  onSize: (value: string) => void;
  count: number;
  onCount: (value: number) => void;
  parent: ImageOut | null;
  onClearParent: () => void;
  region: Region | null;
  onRegion: (region: Region | null) => void;
  styleId: string | null;
  linkConsistency: boolean;
  onStyle: (styleId: string | null) => void;
  onLinkConsistency: (value: boolean) => void;
  busy: boolean;
  uploading: boolean;
  onUpload: (file: File) => void;
  onUploadError: (message: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  diagramTitle: string | null;
  structureInvalid: boolean;
  structureOpen: boolean;
  onStructure: () => void;
  mode: "auto" | "generate" | "edit";
  onMode: (value: "auto" | "generate" | "edit") => void;
  hasImages: boolean;
}

export function Composer({
  prompt,
  onPrompt,
  models,
  modelId,
  onModel,
  size,
  onSize,
  count,
  onCount,
  parent,
  onClearParent,
  region,
  onRegion,
  styleId,
  linkConsistency,
  onStyle,
  onLinkConsistency,
  busy,
  uploading,
  onUpload,
  onUploadError,
  onSubmit,
  onStop,
  diagramTitle, structureInvalid, structureOpen, onStructure, mode, onMode, hasImages,
}: Props) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const model = models.find((m) => m.id === modelId);
  const canSend = !!(prompt.trim() || diagramTitle?.trim()) && !structureInvalid && !busy && !uploading;

  function attach(files: File[]) {
    if (busy || uploading) return;
    if (files.length !== 1) {
      onUploadError("Attach one image at a time.");
      return;
    }
    const file = files[0];
    if (!/\.(png|jpe?g|webp)$/i.test(file.name) &&
        !["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      onUploadError("Choose a PNG, JPEG, or WebP image.");
      return;
    }
    if (!file.size || file.size > 50 * 1024 * 1024) {
      onUploadError("Choose an image up to 50 MB.");
      return;
    }
    onUpload(file);
  }

  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, MAX_COMPOSER_HEIGHT);
    el.style.height = `${next}px`;
    // Only allow scrolling once the box has actually stopped growing, otherwise the
    // scrollbar gutter shows as a sliver against the right edge at every height.
    el.style.overflowY = el.scrollHeight > MAX_COMPOSER_HEIGHT ? "auto" : "hidden";
  }, [prompt]);

  // "/" focuses the composer from anywhere, the way every editor-shaped tool works.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if (event.key === "/" && !typing) {
        event.preventDefault();
        textarea.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="px-4 pb-4 pt-2">
      <div
        className="relative mx-auto w-full max-w-3xl"
        onDragEnter={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          dragDepth.current += 1;
          if (!busy && !uploading) setDragging(true);
        }}
        onDragOver={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = busy || uploading ? "none" : "copy";
        }}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (!dragDepth.current) setDragging(false);
        }}
        onDrop={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          dragDepth.current = 0;
          setDragging(false);
          attach(Array.from(event.dataTransfer.files));
        }}
      >
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          tabIndex={-1}
          aria-label="Choose image to edit"
          disabled={busy || uploading}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (files.length) attach(files);
          }}
        />
        {dragging && (
          <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-2xl border border-accent-fill bg-card text-sm text-foreground">
            <Upload className="size-5 text-accent" />
            Drop an image to edit
            <span className="text-xs text-muted-foreground">PNG, JPEG or WebP · up to 50 MB</span>
          </div>
        )}
        {uploading && (
          <p role="status" className="mb-2 px-2 text-xs text-muted-foreground">
            Preparing your image… You can keep writing your changes.
          </p>
        )}
        {parent && (
          <div className="mx-2 mb-[-10px] flex items-center gap-2.5 rounded-t-xl border border-b-0 border-border bg-background-subtle px-3 pb-4 pt-2.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={parent.gallery_url} alt="" className="size-8 rounded-md object-cover" />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-[11px] font-medium text-accent">
                <Layers className="size-3" />
                Editing this image
              </p>
              <p className="truncate text-[11px] text-subtle-foreground">
                {region
                  ? `Selected ${region.right - region.left}×${region.bottom - region.top}. The edit area may expand to fit the model.`
                  : parent.prompt || `Uploaded image · ${parent.width}×${parent.height}`}
              </p>
            </div>
            <RegionPicker image={parent} value={region} onChange={onRegion} />
            <Tooltip label="Stop editing">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onClearParent}
                aria-label="Stop editing this image"
              >
                <X />
              </Button>
            </Tooltip>
          </div>
        )}

        {diagramTitle !== null && <button type="button" onClick={onStructure}
          className="mb-2 flex max-w-full cursor-pointer items-center gap-2 px-2 py-1 text-xs text-accent">
          <GitBranch className="size-3.5 shrink-0" />
          <span className="truncate">{diagramTitle || "Untitled structure"}</span>
          {structureInvalid && <span className="shrink-0 text-danger">Needs attention</span>}
        </button>}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) onSubmit();
          }}
          className="relative rounded-2xl border border-border bg-card transition-colors duration-200 focus-within:border-border-strong"
        >
          <label htmlFor="prompt" className="sr-only">
            Prompt
          </label>
          <textarea
            id="prompt"
            ref={textarea}
            rows={1}
            value={prompt}
            onChange={(e) => onPrompt(e.target.value)}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files);
              if (files.length) {
                event.preventDefault();
                attach(files);
              }
            }}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter is a newline — what every chat surface does.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (canSend) onSubmit();
              }
            }}
            placeholder={
              region
                ? "Describe the change to this area…"
                : parent
                  ? "Describe the change…"
                  : "Describe the image you want…"
            }
            className="block max-h-[320px] w-full resize-none bg-transparent pb-2 pl-4 pr-14 pt-3.5 text-[15px] leading-relaxed text-foreground outline-none placeholder:text-subtle-foreground sm:pr-4"
          />

          <div className="flex flex-wrap items-center gap-1.5 px-2.5 pb-2.5">
            <Tooltip label="Attach image">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Attach image"
                disabled={busy || uploading}
                onClick={() => fileInput.current?.click()}
              >
                <ImagePlus />
              </Button>
            </Tooltip>
            <Select value={modelId} onValueChange={onModel}>
              <SelectTrigger aria-label="Model" className="max-w-[10rem]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>Model</SelectLabel>
                {models.map((m) => (
                  <SelectItem key={m.id} value={m.id} hint={m.provider.split("-")[0]}>
                    {m.id}
                  </SelectItem>
                ))}
                </SelectGroup>
              </SelectContent>
            </Select>

            <Select value={size} onValueChange={onSize}>
              <SelectTrigger aria-label="Output size">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>Output size</SelectLabel>
                {(model?.sizes ?? ["1k"]).map((preset) => (
                  <SelectItem key={preset} value={preset} hint={SIZE_HINTS[preset]}>
                    {preset}
                  </SelectItem>
                ))}
                </SelectGroup>
              </SelectContent>
            </Select>

            <Select value={String(count)} onValueChange={(v) => onCount(Number(v))}>
              <SelectTrigger aria-label="Number of candidates">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>Candidates</SelectLabel>
                {Array.from({ length: model?.max_n_per_request ?? 1 }, (_, i) => i + 1).map(
                  (value) => (
                    <SelectItem key={value} value={String(value)}>
                      {value === 1 ? "1 image" : `${value} images`}
                    </SelectItem>
                  ),
                )}
                </SelectGroup>
              </SelectContent>
            </Select>

            <Button type="button" variant="ghost" size="sm" aria-pressed={structureOpen}
              disabled={busy || uploading} onClick={onStructure}><GitBranch />Structure</Button>

            <Select value={mode} onValueChange={(value) => onMode(value as typeof mode)} disabled={busy || uploading}>
              <SelectTrigger aria-label="Generation mode"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto</SelectItem>
                <SelectItem value="generate">New image</SelectItem>
                <SelectItem value="edit" disabled={!hasImages && !parent}>{parent ? "Edit selected" : "Edit latest"}</SelectItem>
              </SelectContent>
            </Select>

            <StylePanel
              activeStyleId={styleId}
              linkConsistency={linkConsistency}
              disabled={busy}
              onPick={onStyle}
              onLinkConsistency={onLinkConsistency}
            />

            <div className="absolute right-2.5 top-2.5 flex items-center gap-1.5 sm:static sm:ml-auto">
              {busy ? (
                <Tooltip label="Stop watching progress">
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    onClick={onStop}
                    aria-label="Stop watching progress"
                    className="rounded-full"
                  >
                    <Square className="fill-current" />
                  </Button>
                </Tooltip>
              ) : (
                <Tooltip label="Send" keys={["↵"]}>
                  <Button
                    type="submit"
                    variant="primary"
                    size="icon"
                    disabled={!canSend}
                    aria-label="Send prompt"
                    className={cn(
                      "rounded-full transition-opacity",
                      !canSend && "opacity-40",
                    )}
                  >
                    <ArrowUp />
                  </Button>
                </Tooltip>
              )}
            </div>
          </div>
        </form>

        <p className="mt-2 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-[11px] text-subtle-foreground">
          <span className="inline-flex items-center gap-1">
            <kbd className="rounded border border-border bg-card px-1 py-px text-[10px]">
              ⇧↵
            </kbd>
            newline
          </span>
          <span aria-hidden>·</span>
          <span className="inline-flex items-center gap-1">
            <kbd className="rounded border border-border bg-card px-1 py-px text-[10px]">
              /
            </kbd>
            focus
          </span>
          <span aria-hidden>·</span>
          <span>Drop or paste an image to edit</span>
        </p>
      </div>
    </div>
  );
}
