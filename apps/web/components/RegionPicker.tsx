"use client";

import { Check, Frame, RotateCcw } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import type { ImageOut, Region } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

interface Props {
  image: ImageOut;
  value: Region | null;
  onChange: (region: Region | null) => void;
}

type Drag = { x0: number; y0: number; x1: number; y1: number };

function normalise(drag: Drag) {
  return {
    left: Math.min(drag.x0, drag.x1),
    top: Math.min(drag.y0, drag.y1),
    right: Math.max(drag.x0, drag.x1),
    bottom: Math.max(drag.y0, drag.y1),
  };
}

/**
 * Draw a rectangle over the image to edit only that part.
 *
 * Coordinates are captured as fractions of the displayed element and converted to
 * parent-image pixels on confirm, so the picker does not care what resolution the
 * browser chose to render — it works identically on the 2048px viewer derivative and
 * on a phone.
 *
 * The selection is a hint, not a contract: the server grows it to a size the model
 * accepts and snaps it onto whitespace. The note in the footer says so, because a
 * user who draws a tight box and gets a wider edit should know why.
 */
export function RegionPicker({ image, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const surface = useRef<HTMLDivElement>(null);

  const point = useCallback((event: React.PointerEvent) => {
    const box = surface.current?.getBoundingClientRect();
    if (!box) return { x: 0, y: 0 };
    return {
      x: Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
      y: Math.min(1, Math.max(0, (event.clientY - box.top) / box.height)),
    };
  }, []);

  const selection = drag ? normalise(drag) : null;
  const big = selection && selection.right - selection.left > 0.02;

  function confirm() {
    if (!selection || !big) return;
    onChange({
      left: Math.round(selection.left * image.width),
      top: Math.round(selection.top * image.height),
      right: Math.round(selection.right * image.width),
      bottom: Math.round(selection.bottom * image.height),
    });
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm" className="gap-1.5">
          <Frame />
          {value ? `${value.right - value.left}×${value.bottom - value.top}` : "Select area"}
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-3xl p-3">
        <DialogTitle className="px-1 pb-2 text-[13px] font-medium">
          Drag to choose the area to edit
        </DialogTitle>

        <div
          ref={surface}
          onPointerDown={(event) => {
            (event.target as HTMLElement).setPointerCapture(event.pointerId);
            const { x, y } = point(event);
            setDrag({ x0: x, y0: y, x1: x, y1: y });
          }}
          onPointerMove={(event) => {
            if (!drag) return;
            const { x, y } = point(event);
            setDrag({ ...drag, x1: x, y1: y });
          }}
          className="relative cursor-crosshair select-none overflow-hidden rounded-xl border border-border"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={image.viewer_url}
            alt={image.prompt}
            draggable={false}
            className="w-full select-none"
            style={{ aspectRatio: `${image.width} / ${image.height}` }}
          />

          {selection && (
            <>
              {/* Dim everything outside the selection so the choice is legible. */}
              <div
                className="pointer-events-none absolute inset-0 bg-background/65"
                style={{
                  clipPath: `polygon(0 0, 100% 0, 100% 100%, 0 100%, 0 0,
                    ${selection.left * 100}% ${selection.top * 100}%,
                    ${selection.left * 100}% ${selection.bottom * 100}%,
                    ${selection.right * 100}% ${selection.bottom * 100}%,
                    ${selection.right * 100}% ${selection.top * 100}%,
                    ${selection.left * 100}% ${selection.top * 100}%)`,
                }}
              />
              <div
                className="pointer-events-none absolute border-2 border-accent-fill"
                style={{
                  left: `${selection.left * 100}%`,
                  top: `${selection.top * 100}%`,
                  width: `${(selection.right - selection.left) * 100}%`,
                  height: `${(selection.bottom - selection.top) * 100}%`,
                }}
              />
            </>
          )}
        </div>

        <div className="flex items-center gap-2 px-1 pt-2.5">
          <p className="flex-1 text-[11px] leading-relaxed text-subtle-foreground">
            The area is widened to a size the model accepts and snapped onto whitespace,
            so the edit may cover slightly more than you draw. Everything outside it stays
            byte-identical.
          </p>
          {value && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                onChange(null);
                setDrag(null);
                setOpen(false);
              }}
            >
              <RotateCcw />
              Clear
            </Button>
          )}
          <Button variant="primary" size="sm" disabled={!big} onClick={confirm}>
            <Check />
            Use this area
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
