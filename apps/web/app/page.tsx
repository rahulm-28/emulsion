"use client";

import { PanelLeft, PanelRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AuthGate } from "@/components/AuthGate";
import { Composer } from "@/components/Composer";
import { DiagramEditor } from "@/components/DiagramEditor";
import { Inspector } from "@/components/Inspector";
import { LogoMark } from "@/components/Logo";
import { Sidebar } from "@/components/Sidebar";
import { Thread } from "@/components/Thread";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Tooltip } from "@/components/ui/tooltip";
import { diagramIssues, emptyDiagram, type DiagramSpec } from "@/lib/diagram";
import {
  createJob,
  deleteSession,
  getHealth,
  getJob,
  listModels,
  listSessionJobs,
  listSessions,
  patchSession,
  renameSession,
  streamJob,
  uploadImage,
  type CreateJobBody,
  type HealthOut,
  type ImageOut,
  type JobOut,
  type ModelOut,
  type Region,
  type SessionOut,
} from "@/lib/api";

const SUGGESTIONS = [
  {
    title: "Architecture diagram",
    prompt:
      "A four-zone system architecture diagram, labelled, flat vector, generous whitespace gutters between zones",
  },
  {
    title: "Technical illustration",
    prompt:
      "An exploded isometric view of a mechanical keyboard switch, technical illustration, thin line weights",
  },
  {
    title: "Editorial chart",
    prompt:
      "A muted editorial chart showing quarterly revenue, clean sans-serif labels, no gridlines",
  },
];

export default function Page() {
  return (
    <AuthGate>
      <Studio />
    </AuthGate>
  );
}

function Studio() {
  const [models, setModels] = useState<ModelOut[]>([]);
  const [health, setHealth] = useState<HealthOut | null>(null);
  const [sessions, setSessions] = useState<SessionOut[]>([]);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionReload, setSessionReload] = useState(0);
  const [jobs, setJobs] = useState<JobOut[]>([]);

  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState("gpt-image-2");
  const [size, setSize] = useState("1k");
  const [count, setCount] = useState(1);
  const [parent, setParent] = useState<ImageOut | null>(null);
  const [region, setRegion] = useState<Region | null>(null);
  const [diagram, setDiagram] = useState<DiagramSpec | null>(null);
  const [structureOpen, setStructureOpen] = useState(false);
  const [mode, setMode] = useState<"auto" | "generate" | "edit">("auto");
  const [desktop, setDesktop] = useState(false);
  // A style can be chosen before the conversation exists; it is applied to the session
  // the moment one is created.
  const [pendingStyleId, setPendingStyleId] = useState<string | null>(null);
  const [pendingLink, setPendingLink] = useState(false);

  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ImageOut | null>(null);

  const [navOpen, setNavOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);

  const unsubscribe = useRef<null | (() => void)>(null);
  const uploadController = useRef<AbortController | null>(null);
  const conversationEpoch = useRef(0);
  const submitting = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);

  const model = models.find((m) => m.id === modelId) ?? null;
  const activeSession = sessions.find((s) => s.id === sessionId) ?? null;
  const selectedJob = jobs.find((j) => j.images.some((i) => i.id === selected?.id)) ?? null;

  const refreshSessions = useCallback(async () => {
    setSessions(await listSessions());
  }, []);

  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    const update = () => setDesktop(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    listModels()
      .then((found) => {
        setModels(found);
        if (found[0]) setModelId(found[0].id);
      })
      .catch((e) => setError(String(e)));
    getHealth().then(setHealth).catch(() => undefined);
    refreshSessions().catch((e) => setError(String(e)));
    return () => {
      unsubscribe.current?.();
      uploadController.current?.abort();
    };
  }, [refreshSessions]);

  useEffect(() => {
    if (!sessionId) {
      setJobs([]);
      return;
    }
    let live = true;
    listSessionJobs(sessionId)
      .then((found) => {
        if (!live) return;
        setJobs((current) => {
          const merged = found.map((job) => {
            const local = current.find((item) => item.id === job.id);
            return local && (local.status === "succeeded" || local.status === "failed") ? local : job;
          });
          return [...merged, ...current.filter((job) => job.session_id === sessionId && !found.some((item) => item.id === job.id))];
        });
        setSelected(found.at(-1)?.images.at(-1) ?? null);
        setPendingStyleId(null);
        setPendingLink(false);
        const running = [...found].reverse().find((job) => job.status === "queued" || job.status === "running");
        if (running) {
          setUploading(running.kind === "upload");
          setBusy(running.kind !== "upload");
          watchJob(running);
        }
      })
      .catch(() => live && setError("Could not load this conversation. Try opening it again."));
    return () => {
      live = false;
    };
  }, [sessionId, sessionReload]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [jobs.length, busy]);

  function upsertJob(next: JobOut) {
    setJobs((prev) => {
      const index = prev.findIndex((j) => j.id === next.id);
      if (index === -1) return [...prev, next];
      const copy = [...prev];
      copy[index] = next;
      return copy;
    });
  }

  function watchJob(created: JobOut) {
    const epoch = conversationEpoch.current;
    unsubscribe.current?.();
    unsubscribe.current = streamJob(created.id, {
      onMessage: (kind, message, seq) => {
        if (epoch !== conversationEpoch.current) return;
        setJobs((previous) => previous.map((job) => job.id !== created.id ? job : {
          ...job,
          status: kind === "error" ? "failed" : message === "queued" ? "queued" : "running",
          events: [...job.events, {
            seq, kind, message, created_at: new Date().toISOString(),
          }],
        }));
      },
      onSnapshot: (job) => { if (epoch === conversationEpoch.current) upsertJob(job); },
      onDone: (finished) => {
        if (epoch !== conversationEpoch.current) return;
        upsertJob(finished);
        setBusy(false);
        setUploading(false);
        if (finished.status === "failed") setError(finished.error ?? "Could not finish this request.");
        const image = finished.images.at(0);
        if (image) {
          setSelected(image);
          if (finished.kind === "upload") {
            setParent(image);
            setRegion(null);
            setMode("edit");
          }
        }
        refreshSessions().catch(() => undefined);
        getHealth().then(setHealth).catch(() => undefined);
      },
      onError: (message) => {
        if (epoch !== conversationEpoch.current) return;
        setError(message);
        setBusy(false);
        setUploading(false);
      },
    }, created.events.at(-1)?.seq ?? -1);
  }

  async function attachImage(file: File) {
    if (busy || uploading) return;
    const epoch = conversationEpoch.current;
    const controller = new AbortController();
    uploadController.current?.abort();
    uploadController.current = controller;
    setUploading(true);
    setError(null);
    try {
      const created = await uploadImage(file, sessionId, controller.signal);
      if (epoch !== conversationEpoch.current) return;
      setSessionId(created.session_id);
      upsertJob(created);
      if (!sessionId && created.session_id && (pendingStyleId || pendingLink)) {
        await patchSession(created.session_id, {
          style_id: pendingStyleId ?? "", link_consistency: pendingLink,
        });
      }
      if (epoch !== conversationEpoch.current) return;
      refreshSessions().catch(() => undefined);
      watchJob(created);
    } catch (error) {
      if (epoch !== conversationEpoch.current || controller.signal.aborted) return;
      setError(error instanceof Error ? error.message : "Could not upload this image.");
      setUploading(false);
    }
  }

  function leaveConversation() {
    conversationEpoch.current += 1;
    uploadController.current?.abort();
    unsubscribe.current?.();
    setUploading(false);
    setBusy(false);
    setParent(null);
    setRegion(null);
    setDiagram(null);
    setStructureOpen(false);
    setMode("auto");
    setPrompt("");
    setInspectorOpen(false);
    setError(null);
  }

  async function submit() {
    const text = prompt.trim() || diagram?.title.trim() || "";
    if (!text || (diagram && diagramIssues(diagram).length)) return;
    await submitBody({
      prompt: text, model_id: modelId, size, n: count,
      parent_image_id: parent?.id ?? null, region: parent ? region : null,
      session_id: sessionId, diagram, mode: parent ? "edit" : mode,
      style_id: activeSession?.style_id ?? pendingStyleId,
      link_consistency: activeSession?.link_consistency ?? pendingLink,
    });
  }

  async function submitBody(body: CreateJobBody) {
    if (busy || uploading || submitting.current) return;
    submitting.current = true;
    const epoch = conversationEpoch.current;
    unsubscribe.current?.();
    setBusy(true);
    setError(null);

    try {
      const created = await createJob(body);

      if (epoch !== conversationEpoch.current) return;
      setSessionId(created.session_id);
      upsertJob(created);
      setPrompt("");
      setParent(null);
      setRegion(null);
      setDiagram(null);
      setStructureOpen(false);
      setMode("auto");
      refreshSessions().catch(() => undefined);

      if (epoch !== conversationEpoch.current) return;
      watchJob(created);
    } catch (e) {
      if (epoch !== conversationEpoch.current) return;
      setError(e instanceof Error ? e.message : String(e));
      setPrompt(body.prompt);
      setBusy(false);
    } finally {
      submitting.current = false;
    }
  }

  /**
   * Stop watching, not stop generating. The worker has no HTTP request above it and
   * will finish regardless — pretending otherwise would be a lie, so the job is
   * re-read once rather than abandoned.
   */
  function stopWatching() {
    const epoch = conversationEpoch.current;
    unsubscribe.current?.();
    unsubscribe.current = null;
    setBusy(false);
    const running = jobs.at(-1);
    if (running) {
      getJob(running.id).then((job) => {
        if (epoch === conversationEpoch.current) upsertJob(job);
      }).catch(() => undefined);
    }
  }

  /**
   * Run the same prompt again. Same session, same parameters, new idempotency key —
   * the point of a rerun is a different sample, so reusing the key would return the
   * original job and look like nothing happened.
   */
  function rerun(job: JobOut) {
    void submitBody({
      prompt: job.prompt, model_id: job.model_id, size: job.size, n: job.n,
      parent_image_id: job.parent_image_id, region: job.region, diagram: job.diagram,
      session_id: job.session_id, mode: job.parent_image_id ? "edit" : "generate",
    });
  }

  function editImage(image: ImageOut) {
    setParent(image);
    setSelected(image);
    setRegion(null);
    setMode("edit");
    setStructureOpen(false);
    if (!desktop) setInspectorOpen(false);
  }

  function startNew() {
    leaveConversation();
    setSessionId(null);
    setJobs([]);
    setSelected(null);
    setParent(null);
    setRegion(null);
    setError(null);
    setBusy(false);
    setNavOpen(false);
  }

  async function handleDelete(id: string) {
    await deleteSession(id);
    if (id === sessionId) startNew();
    refreshSessions().catch(() => undefined);
  }

  async function applyStyle(styleId: string | null) {
    setPendingStyleId(styleId);
    if (!sessionId) return;
    await patchSession(sessionId, { style_id: styleId ?? "" });
    refreshSessions().catch(() => undefined);
  }

  async function applyLinkConsistency(value: boolean) {
    setPendingLink(value);
    if (!sessionId) return;
    await patchSession(sessionId, { link_consistency: value });
    refreshSessions().catch(() => undefined);
  }

  async function handleRename(id: string, title: string) {
    await renameSession(id, title);
    refreshSessions().catch(() => undefined);
  }

  return (
    <div className="flex h-[100dvh] overflow-hidden">
      <Sidebar
        sessions={sessions}
        activeId={sessionId}
        health={health}
        open={navOpen}
        onClose={() => setNavOpen(false)}
        onSelect={(id) => {
          leaveConversation();
          setSessionId(id);
          setSessionReload((value) => value + 1);
          setNavOpen(false);
        }}
        onNew={startNew}
        onRename={handleRename}
        onDelete={handleDelete}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            className="lg:hidden"
          >
            <PanelLeft />
          </Button>

          <div className="min-w-0 flex-1 px-1">
            <h1 className="truncate text-[13px] font-medium text-foreground">
              {activeSession?.title ?? "New generation"}
            </h1>
            {activeSession && (
              <p className="truncate font-mono text-[10px] text-subtle-foreground">
                {activeSession.job_count} generation
                {activeSession.job_count === 1 ? "" : "s"} · {activeSession.model_id}
              </p>
            )}
          </div>

          <Tooltip label={inspectorOpen ? "Hide inspector" : "Show inspector"}>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setInspectorOpen((v) => !v)}
              aria-label={inspectorOpen ? "Hide inspector" : "Show inspector"}
              aria-pressed={inspectorOpen}
              className={inspectorOpen ? "text-foreground" : undefined}
            >
              <PanelRight />
            </Button>
          </Tooltip>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {structureOpen && diagram ? (
            <DiagramEditor diagram={diagram} onChange={setDiagram}
              onClose={() => setStructureOpen(false)}
              onRemove={() => { setDiagram(null); setStructureOpen(false); }}
              prompt={prompt} modelId={modelId} styleId={activeSession?.style_id ?? pendingStyleId} />
          ) : jobs.length === 0 ? (
            <EmptyState onPick={setPrompt} />
          ) : (
            <Thread
              jobs={jobs}
              selectedImageId={selected?.id ?? null}
              onSelectImage={(image) => {
                setSelected(image);
                setInspectorOpen(true);
              }}
              onEdit={editImage}
              onRerun={rerun}
              onUseDiagram={(job) => {
                setDiagram(structuredClone(job.diagram));
                setPrompt(job.prompt);
                setModelId(job.model_id);
                setSize(job.size);
                setCount(job.n);
                setParent(null);
                setRegion(null);
                setMode("generate");
                setStructureOpen(true);
              }}
            />
          )}
          <div ref={bottom} />
        </div>

        {error && (
          <div
            role="alert"
            className="mx-auto w-full max-w-3xl px-4 pb-1 text-xs text-danger"
          >
            {error}
          </div>
        )}

        <Composer
          prompt={prompt}
          onPrompt={setPrompt}
          models={models}
          modelId={modelId}
          onModel={setModelId}
          size={size}
          onSize={setSize}
          count={count}
          onCount={setCount}
          parent={parent}
          onClearParent={() => {
            setParent(null);
            setRegion(null);
            setMode("generate");
          }}
          region={region}
          onRegion={setRegion}
          styleId={activeSession?.style_id ?? pendingStyleId}
          linkConsistency={activeSession?.link_consistency ?? pendingLink}
          onStyle={applyStyle}
          onLinkConsistency={applyLinkConsistency}
          busy={busy}
          uploading={uploading}
          onUpload={attachImage}
          onUploadError={setError}
          diagramTitle={diagram?.title ?? null}
          structureInvalid={!!diagram && diagramIssues(diagram).length > 0}
          structureOpen={structureOpen}
          onStructure={() => { if (!diagram) setDiagram(emptyDiagram()); setStructureOpen(!structureOpen); }}
          mode={mode}
          onMode={(value) => {
            setMode(value);
            if (value !== "edit") { setParent(null); setRegion(null); }
          }}
          hasImages={jobs.some((job) => job.images.length > 0)}
          onSubmit={submit}
          onStop={stopWatching}
        />
      </main>

      {desktop ? <div className="h-full">
        <Inspector
          image={selected}
          job={selectedJob}
          model={models.find((item) => item.id === selected?.model_id) ?? model}
          open={inspectorOpen}
          onClose={() => setInspectorOpen(false)}
          onSelect={setSelected}
          onEdit={editImage}
        />
      </div> : <Dialog open={inspectorOpen} onOpenChange={setInspectorOpen}>
        <DialogContent hideClose className="h-[85dvh] max-w-md overflow-hidden p-0">
          <DialogTitle className="sr-only">Image inspector</DialogTitle>
          <DialogDescription className="sr-only">Inspect, export, or edit your selected image.</DialogDescription>
          <Inspector image={selected} job={selectedJob}
            model={models.find((item) => item.id === selected?.model_id) ?? model}
            open={inspectorOpen} onClose={() => setInspectorOpen(false)} onSelect={setSelected} onEdit={editImage} />
        </DialogContent>
      </Dialog>}
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="mx-auto flex h-full w-full max-w-2xl flex-col items-center justify-center px-6 text-center">
      <LogoMark className="size-9 text-accent-fill" />
      <h2 className="mt-6 font-serif text-[34px] leading-tight tracking-tight text-foreground">
        Same model, better layer.
      </h2>
      <p className="mt-3 max-w-sm text-[13px] leading-relaxed text-muted-foreground">
        Describe an image, or attach one and tell us what to change.
        Keep every version in the same conversation.
      </p>

      <div className="mt-9 grid w-full gap-2 sm:grid-cols-3">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion.title}
            type="button"
            onClick={() => onPick(suggestion.prompt)}
            className="group cursor-pointer rounded-xl border border-border bg-card p-3 text-left transition-colors duration-200 hover:border-border-strong hover:bg-background-subtle"
          >
            <span className="block text-[12px] font-medium text-foreground">
              {suggestion.title}
            </span>
            <span className="mt-1 block line-clamp-3 text-[11px] leading-relaxed text-subtle-foreground">
              {suggestion.prompt}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
