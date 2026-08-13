"use client";

import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import * as React from "react";
import { cn } from "@/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;
export const TooltipRoot = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "pop-in lift z-[30] rounded-lg border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = "TooltipContent";

/** Label plus optional keyboard hint, so shortcuts are discoverable rather than folklore. */
export function Tooltip({
  label,
  keys,
  children,
  side = "top",
}: {
  label: string;
  keys?: string[];
  children: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
}) {
  return (
    <TooltipRoot>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side}>
        <span className="flex items-center gap-1.5">
          {label}
          {keys?.map((key) => (
            <kbd
              key={key}
              className="rounded border border-border bg-background-subtle px-1 py-px font-sans text-[10px] text-subtle-foreground"
            >
              {key}
            </kbd>
          ))}
        </span>
      </TooltipContent>
    </TooltipRoot>
  );
}
