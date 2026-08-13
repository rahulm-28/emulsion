"use client";

import { Check, Lightbulb, Palette, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  createStyle,
  deleteStyle,
  listStyles,
  listSuggestions,
  updateStyle,
  type StyleOut,
  type SuggestionOut,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface Props {
  activeStyleId: string | null;
  linkConsistency: boolean;
  disabled: boolean;
  onPick: (styleId: string | null) => void;
  onLinkConsistency: (value: boolean) => void;
}

/**
 * House styles and the constraints the tool has noticed you repeating.
 *
 * Suggestions are never applied on their own — they are promoted into a named style by
 * hand. A constraint that silently attached itself to your prompts would be impossible
 * to debug the day it makes a picture worse.
 */
export function StylePanel({
  activeStyleId,
  linkConsistency,
  disabled,
  onPick,
  onLinkConsistency,
}: Props) {
  const [open, setOpen] = useState(false);
  const [styles, setStyles] = useState<StyleOut[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestionOut[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const active = styles.find((s) => s.id === activeStyleId) ?? null;

  useEffect(() => {
    if (!open) return;
    listStyles().then(setStyles).catch(() => setStyles([]));
    listSuggestions().then(setSuggestions).catch(() => setSuggestions([]));
  }, [open]);

  async function refresh() {
    setStyles(await listStyles());
  }

  async function addStyle() {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      const created = await createStyle({ name: trimmed });
      setName("");
      await refresh();
      onPick(created.id);
    } finally {
      setBusy(false);
    }
  }

  async function promote(suggestion: SuggestionOut) {
    if (!active) return;
    if (active.rules.includes(suggestion.text)) return;
    await updateStyle(active.id, { ...active, rules: [...active.rules, suggestion.text] });
    await refresh();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="secondary"
          size="sm"
          disabled={disabled}
          className={cn("gap-1.5", active && "border-accent-fill/50 text-accent")}
        >
          <Palette />
          {active ? active.name : "Style"}
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-lg p-4">
        <DialogTitle className="text-[13px] font-medium">House style</DialogTitle>
        <p className="mt-1 text-[11px] leading-relaxed text-subtle-foreground">
          Defaults every diagram in this conversation inherits — a colour legend, extra
          rules, a layout. Anything you type for a single diagram still wins.
        </p>

        <div className="mt-4 space-y-1">
          <button
            type="button"
            onClick={() => onPick(null)}
            className={cn(
              "flex w-full cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors duration-200",
              activeStyleId === null
                ? "border-accent-fill text-foreground"
                : "border-border text-muted-foreground hover:border-border-strong",
            )}
          >
            {activeStyleId === null && <Check className="size-3.5 text-accent" />}
            No style
          </button>

          {styles.map((style) => (
            <div key={style.id} className="group relative">
              <button
                type="button"
                onClick={() => onPick(style.id)}
                className={cn(
                  "flex w-full cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 pr-10 text-left text-xs transition-colors duration-200",
                  style.id === activeStyleId
                    ? "border-accent-fill text-foreground"
                    : "border-border text-muted-foreground hover:border-border-strong",
                )}
              >
                {style.id === activeStyleId && <Check className="size-3.5 text-accent" />}
                <span className="min-w-0 flex-1 truncate">{style.name}</span>
                <span className="font-mono text-[10px] text-subtle-foreground">
                  {style.rules.length} rule{style.rules.length === 1 ? "" : "s"}
                </span>
              </button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Delete ${style.name}`}
                onClick={async () => {
                  await deleteStyle(style.id);
                  if (style.id === activeStyleId) onPick(null);
                  await refresh();
                }}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
              >
                <Trash2 />
              </Button>
            </div>
          ))}
        </div>

        <div className="mt-3 flex gap-2">
          <label htmlFor="style-name" className="sr-only">
            New style name
          </label>
          <input
            id="style-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addStyle()}
            placeholder="New style name"
            className="h-9 flex-1 rounded-lg border border-border bg-card px-3 text-xs outline-none transition-colors duration-200 placeholder:text-subtle-foreground focus:border-border-strong"
          />
          <Button variant="secondary" size="md" onClick={addStyle} disabled={!name.trim()}>
            <Plus />
            Add
          </Button>
        </div>

        <label className="mt-4 flex cursor-pointer items-start gap-2.5 rounded-lg border border-border p-3">
          <input
            type="checkbox"
            checked={linkConsistency}
            onChange={(e) => onLinkConsistency(e.target.checked)}
            className="mt-0.5 size-3.5 cursor-pointer accent-[var(--accent-fill)]"
          />
          <span>
            <span className="block text-xs text-foreground">Match the previous diagram</span>
            <span className="mt-0.5 block text-[11px] leading-relaxed text-subtle-foreground">
              Asks for the same layout and legend as the last picture in this
              conversation, so a set reads as a deck. Off for scratch work.
            </span>
          </span>
        </label>

        {suggestions.length > 0 && (
          <section className="mt-4">
            <h3 className="mb-1.5 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.13em] text-subtle-foreground">
              <Lightbulb className="size-3" />
              Noticed you repeating
            </h3>
            <ul className="space-y-1">
              {suggestions.slice(0, 5).map((suggestion) => {
                const already = active?.rules.includes(suggestion.text);
                return (
                  <li
                    key={suggestion.text}
                    className="flex items-center gap-2 rounded-lg border border-border px-3 py-2"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs text-foreground">
                        {suggestion.text}
                      </span>
                      <span className="font-mono text-[10px] text-subtle-foreground">
                        in {suggestion.occurrences} prompts
                      </span>
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!active || already}
                      onClick={() => promote(suggestion)}
                      title={active ? undefined : "Select a style first"}
                    >
                      {already ? "Added" : "Add to style"}
                    </Button>
                  </li>
                );
              })}
            </ul>
            <p className="mt-1.5 text-[10px] leading-relaxed text-subtle-foreground">
              Nothing here is applied until you add it. Suggestions come from counting
              clauses in your own prompts — no model is guessing at your taste.
            </p>
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}
