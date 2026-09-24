"use client";

import { MoreHorizontal, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { HealthOut, SessionOut } from "@/lib/api";
import { BUCKET_ORDER, bucketFor, formatCost } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { AccountButton } from "./AccountButton";
import { Wordmark } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";

interface Props {
  sessions: SessionOut[];
  activeId: string | null;
  health: HealthOut | null;
  open: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

export function Sidebar({
  sessions,
  activeId,
  health,
  open,
  onClose,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: Props) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matched = needle
      ? sessions.filter((s) => s.title.toLowerCase().includes(needle))
      : sessions;
    const buckets = new Map<string, SessionOut[]>();
    for (const session of matched) {
      const key = bucketFor(session.updated_at);
      buckets.set(key, [...(buckets.get(key) ?? []), session]);
    }
    return BUCKET_ORDER.filter((k) => buckets.has(k)).map(
      (k) => [k, buckets.get(k)!] as const,
    );
  }, [sessions, query]);

  function commitRename(id: string) {
    const title = draft.trim();
    if (title) onRename(id, title);
    setEditing(null);
  }

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="fixed inset-0 z-[20] cursor-default bg-background/70 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-[20] flex w-[278px] shrink-0 flex-col border-r border-border bg-background-subtle transition-transform duration-200 lg:static lg:translate-x-0",
          open ? "visible translate-x-0" : "invisible -translate-x-full lg:visible",
        )}
      >
        <div className="flex h-14 items-center justify-between px-4">
          <Wordmark />
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="Close navigation"
            className="lg:hidden"
          >
            <X />
          </Button>
        </div>

        <div className="space-y-2 px-3 pb-2">
          <Button variant="primary" size="lg" onClick={onNew} className="w-full">
            <Plus />
            New generation
          </Button>

          <div className="relative">
            <label htmlFor="session-search" className="sr-only">
              Search conversations
            </label>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
            <input
              id="session-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search"
              className="h-9 w-full rounded-lg border border-border bg-card pl-8 pr-3 text-[13px] text-foreground outline-none transition-colors duration-200 placeholder:text-subtle-foreground focus:border-border-strong"
            />
          </div>
        </div>

        <nav
          aria-label="Conversations"
          className="min-h-0 flex-1 overflow-y-auto px-2 pb-2"
        >
          {grouped.length === 0 && (
            <p className="px-2 py-8 text-center text-xs text-subtle-foreground">
              {query ? "Nothing matches that." : "No conversations yet."}
            </p>
          )}

          {grouped.map(([bucket, items]) => (
            <section key={bucket} className="mb-1">
              <h2 className="px-2 py-2 text-[10px] font-medium uppercase tracking-[0.13em] text-subtle-foreground">
                {bucket}
              </h2>
              <ul className="space-y-px">
                {items.map((session) => {
                  const active = session.id === activeId;
                  if (editing === session.id) {
                    return (
                      <li key={session.id}>
                        <input
                          autoFocus
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onBlur={() => commitRename(session.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commitRename(session.id);
                            if (e.key === "Escape") setEditing(null);
                          }}
                          aria-label="Conversation title"
                          className="h-[52px] w-full rounded-lg border border-accent-fill bg-card px-3 text-[13px] outline-none"
                        />
                      </li>
                    );
                  }
                  return (
                    <li key={session.id} className="group relative">
                      <button
                        type="button"
                        onClick={() => onSelect(session.id)}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex w-full cursor-pointer items-center gap-2.5 rounded-lg p-2 pr-9 text-left transition-colors duration-200",
                          active
                            ? "bg-card shadow-[0_0_0_1px_var(--border)]"
                            : "hover:bg-card/70",
                        )}
                      >
                        <span
                          className={cn(
                            "grid size-9 shrink-0 place-items-center overflow-hidden rounded-md border bg-background",
                            active ? "border-accent-fill/45" : "border-border",
                          )}
                        >
                          {session.thumbnail_url ? (
                            /* eslint-disable-next-line @next/next/no-img-element */
                            <img
                              src={session.thumbnail_url}
                              alt=""
                              loading="lazy"
                              className="size-full object-cover"
                            />
                          ) : (
                            <span className="size-1.5 rounded-full bg-border-strong" />
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span
                            className={cn(
                              "block truncate text-[13px] leading-snug",
                              active ? "text-foreground" : "text-muted-foreground",
                            )}
                          >
                            {session.title}
                          </span>
                          <span className="mt-0.5 block font-mono text-[10px] text-subtle-foreground">
                            {session.image_count} · {formatCost(session.cost_usd)}
                          </span>
                        </span>
                      </button>

                      <div className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100 data-[open=true]:opacity-100">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Actions for ${session.title}`}
                            >
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onSelect={() => {
                                setEditing(session.id);
                                setDraft(session.title);
                              }}
                            >
                              <Pencil />
                              Rename
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              destructive
                              onSelect={() => onDelete(session.id)}
                            >
                              <Trash2 />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </nav>

        <footer className="flex items-center justify-between gap-2 border-t border-border px-3 py-2.5">
          <Tooltip
            label={
              health?.adapter === "foundry"
                ? "Calls reach the real model and cost money"
                : "Offline adapter — generations are free"
            }
            side="top"
          >
            <span className="flex cursor-default items-center gap-1.5 font-mono text-[10px] text-subtle-foreground">
              <span
                className={cn(
                  "size-1.5 rounded-full",
                  health?.status === "ok" ? "bg-success" : "bg-danger",
                )}
              />
              {health?.adapter ?? "…"}
              {health && health.queue_depth > 0 && <span>· {health.queue_depth} queued</span>}
            </span>
          </Tooltip>
          <div className="flex items-center gap-2">
            <AccountButton />
            <ThemeToggle />
          </div>
        </footer>
      </aside>
    </>
  );
}
