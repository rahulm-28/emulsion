"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Radix Select rather than a native <select>.
 *
 * A native select renders as an OS widget — it cannot be themed, ignores the design
 * system entirely, and looks like a 2005 form control next to everything else.
 */
export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;
/** Radix requires SelectLabel to live inside a group — it labels the group, not the list. */
export const SelectGroup = SelectPrimitive.Group;

export const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-8 cursor-pointer items-center justify-between gap-1.5 rounded-lg border border-border bg-card px-2.5 text-xs text-muted-foreground transition-colors duration-200 hover:border-border-strong hover:text-foreground data-[state=open]:border-border-strong data-[state=open]:text-foreground disabled:pointer-events-none disabled:opacity-50",
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="size-3.5 opacity-60" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = "SelectTrigger";

export const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      position={position}
      sideOffset={6}
      className={cn(
        "pop-in lift z-[50] min-w-[8rem] overflow-hidden rounded-xl border border-border bg-elevated p-1",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.Viewport className="p-0">{children}</SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = "SelectContent";

export const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & { hint?: string }
>(({ className, children, hint, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex cursor-pointer select-none items-center gap-2 rounded-lg py-1.5 pl-2.5 pr-8 text-xs text-muted-foreground outline-none transition-colors duration-150 data-[highlighted]:bg-background-subtle data-[highlighted]:text-foreground data-[state=checked]:text-foreground",
      className,
    )}
    {...props}
  >
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    {hint && <span className="ml-auto font-mono text-[10px] opacity-50">{hint}</span>}
    <span className="absolute right-2.5 flex size-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="size-3.5 text-accent" />
      </SelectPrimitive.ItemIndicator>
    </span>
  </SelectPrimitive.Item>
));
SelectItem.displayName = "SelectItem";

export const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn(
      "px-2.5 pb-1 pt-2 text-[10px] uppercase tracking-[0.12em] text-subtle-foreground",
      className,
    )}
    {...props}
  />
));
SelectLabel.displayName = "SelectLabel";
