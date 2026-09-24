"use client";

import { ArrowLeft, ArrowLeftRight, Eye, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { previewDiagram, type DiagramPreview } from "@/lib/api";
import { diagramIssues, type DiagramComponent, type DiagramSpec } from "@/lib/diagram";

const input = "h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm text-foreground placeholder:text-subtle-foreground focus:border-border-strong";
const label = "flex min-w-0 flex-col gap-1.5 text-xs text-muted-foreground";

function Choice({ value, onChange, options, name }: {
  value: string; onChange: (value: string) => void; options: string[]; name: string;
}) {
  return <Select value={value} onValueChange={onChange}>
    <SelectTrigger aria-label={name} className="h-10 w-full min-w-0">
      <SelectValue placeholder="Choose component" />
    </SelectTrigger>
    <SelectContent>{options.map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent>
  </Select>;
}

export function DiagramEditor({ diagram, onChange, onClose, onRemove, prompt, modelId, styleId }: {
  diagram: DiagramSpec; onChange: (value: DiagramSpec) => void;
  onClose: () => void; onRemove: () => void; prompt: string; modelId: string; styleId: string | null;
}) {
  const [preview, setPreview] = useState<DiagramPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);
  const issues = diagramIssues(diagram);
  const names = [...new Set(diagram.components.map((component) => component.name).filter((name) => name.trim()))];

  useEffect(() => {
    request.current?.abort();
    setPreview(null);
    setError(null);
    setLoading(false);
    return () => request.current?.abort();
  }, [diagram, prompt, modelId, styleId]);

  function updateComponent(index: number, patch: Partial<DiagramComponent>) {
    const oldName = diagram.components[index].name;
    const name = patch.name ?? oldName;
    onChange({
      ...diagram,
      components: diagram.components.map((component, i) => i === index ? { ...component, ...patch } : component),
      connections: diagram.connections.map((link) => ({
        ...link, source: link.source === oldName ? name : link.source,
        target: link.target === oldName ? name : link.target,
      })),
      callouts: diagram.callouts.map((note) => ({ ...note, anchor: note.anchor === oldName ? name : note.anchor })),
    });
  }

  function removeComponent(index: number) {
    const name = diagram.components[index].name;
    onChange({ ...diagram,
      components: diagram.components.filter((_, i) => i !== index),
      connections: diagram.connections.filter((link) => link.source !== name && link.target !== name),
      callouts: diagram.callouts.filter((note) => note.anchor !== name),
    });
  }

  async function showPreview() {
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    setLoading(true);
    setError(null);
    try {
      const result = await previewDiagram(diagram, prompt.trim() || diagram.title, modelId, styleId, controller.signal);
      if (!controller.signal.aborted) setPreview(result);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not preview this diagram.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <section aria-label="Diagram structure editor" className="mx-auto w-full max-w-3xl space-y-7 px-4 py-6">
    <header className="flex items-start justify-between gap-4">
      <div>
        <Button variant="ghost" size="sm" onClick={onClose} className="-ml-2 mb-3"><ArrowLeft />Back to conversation</Button>
        <h2 className="text-xl font-medium text-foreground">Diagram structure</h2>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">Name the parts, connect them, and choose what the diagram should explain.</p>
      </div>
      <Button variant="ghost" size="sm" onClick={onRemove}>Remove structure</Button>
    </header>

    <div className="grid gap-4 sm:grid-cols-2">
      <label className={label}>Diagram title
        <input className={input} value={diagram.title} maxLength={200} onChange={(event) => onChange({ ...diagram, title: event.target.value })} placeholder="How a request becomes a response" />
      </label>
      <label className={label}>Layout
        <input className={input} value={diagram.layout} maxLength={500} onChange={(event) => onChange({ ...diagram, layout: event.target.value })} placeholder="Left to right, grouped by responsibility" />
      </label>
      <label className={`${label} sm:col-span-2`}>Key message
        <textarea className={`${input} min-h-20 py-2`} value={diagram.key_message} maxLength={500} onChange={(event) => onChange({ ...diagram, key_message: event.target.value })} placeholder="The one thing someone should understand at a glance" />
      </label>
    </div>

    <section aria-label="Components" className="space-y-3 border-t border-border pt-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">Components <span className="ml-1 text-subtle-foreground">{diagram.components.length}/40</span></h3>
        <Button variant="secondary" size="sm" disabled={diagram.components.length >= 40} onClick={() => {
          let count = diagram.components.length + 1;
          while (names.includes(`Component ${count}`)) count += 1;
          onChange({ ...diagram, components: [...diagram.components, {
            name: `Component ${count}`, layer: "", role: "", items: [], note: "", emphasis: "normal",
          }] });
        }}><Plus />Add component</Button>
      </div>
      {!diagram.components.length && <p className="text-xs text-muted-foreground">Add a service, process, person, or storage system.</p>}
      {diagram.components.map((component, index) => <div key={index} className="space-y-3 border-b border-border pb-4 last:border-0">
        <div className="grid grid-cols-[1fr_auto] items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <label className={label}>Component {index + 1}
            <input className={input} maxLength={120} value={component.name} onChange={(event) => updateComponent(index, { name: event.target.value })} />
          </label>
          <label className={`${label} col-start-1 row-start-2 sm:col-auto sm:row-auto`}>Group or layer
            <input className={input} maxLength={500} value={component.layer} onChange={(event) => updateComponent(index, { layer: event.target.value })} placeholder="Application" />
          </label>
          <Button variant="ghost" size="icon" aria-label={`Remove component ${index + 1} and its connections`} onClick={() => removeComponent(index)} className="col-start-2 row-start-1 sm:col-auto sm:row-auto"><Trash2 /></Button>
        </div>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer py-1">Details and emphasis</summary>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <label className={label}>Emphasis
              <Choice name={`Emphasis for component ${index + 1}`} value={component.emphasis} options={["normal", "dominant", "aside"]} onChange={(value) => updateComponent(index, { emphasis: value as DiagramComponent["emphasis"] })} />
            </label>
            <label className={label}>Note
              <input className={input} maxLength={500} value={component.note} onChange={(event) => updateComponent(index, { note: event.target.value })} placeholder="What this part does" />
            </label>
          </div>
        </details>
      </div>)}
    </section>

    <section aria-label="Connections" className="space-y-3 border-t border-border pt-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">Connections <span className="ml-1 text-subtle-foreground">{diagram.connections.length}/80</span></h3>
        <Button variant="secondary" size="sm" disabled={names.length < 2 || diagram.connections.length >= 80} onClick={() => onChange({ ...diagram, connections: [...diagram.connections, { source: names[0], target: names[1], label: "", bidirectional: false, weight: "primary" }] })}><Plus />Add connection</Button>
      </div>
      {!diagram.connections.length && <p className="text-xs text-muted-foreground">Connect two components to show what flows between them.</p>}
      {diagram.connections.map((link, index) => <div key={index} className="space-y-2 border-b border-border pb-4 last:border-0">
        <div className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2">
          <Choice name={`Connection ${index + 1} source`} value={link.source} options={names} onChange={(source) => onChange({ ...diagram, connections: diagram.connections.map((item, i) => i === index ? { ...item, source } : item) })} />
          <Button variant="ghost" size="icon" aria-label={`Two-way connection ${index + 1}`} aria-pressed={link.bidirectional} className={link.bidirectional ? "text-accent" : "text-subtle-foreground"} onClick={() => onChange({ ...diagram, connections: diagram.connections.map((item, i) => i === index ? { ...item, bidirectional: !item.bidirectional } : item) })}><ArrowLeftRight /></Button>
          <Choice name={`Connection ${index + 1} target`} value={link.target} options={names} onChange={(target) => onChange({ ...diagram, connections: diagram.connections.map((item, i) => i === index ? { ...item, target } : item) })} />
          <Button variant="ghost" size="icon" aria-label={`Remove connection ${index + 1}`} onClick={() => onChange({ ...diagram, connections: diagram.connections.filter((_, i) => i !== index) })}><Trash2 /></Button>
        </div>
        <label className={label}>Connection {index + 1} label
          <input className={input} maxLength={500} value={link.label} placeholder="Request, response, event…" onChange={(event) => onChange({ ...diagram, connections: diagram.connections.map((item, i) => i === index ? { ...item, label: event.target.value } : item) })} />
        </label>
      </div>)}
    </section>

    <section aria-label="Annotations" className="space-y-3 border-t border-border pt-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">Annotations</h3>
        <Button variant="secondary" size="sm" disabled={!names.length || diagram.callouts.length >= 30} onClick={() => onChange({ ...diagram, callouts: [...diagram.callouts, { anchor: names[0], text: "" }] })}><Plus />Add annotation</Button>
      </div>
      {diagram.callouts.map((note, index) => <div key={index} className="grid grid-cols-[1fr_auto] gap-2 border-b border-border pb-4 last:border-0">
        <Choice name={`Annotation ${index + 1} component`} value={note.anchor} options={names} onChange={(anchor) => onChange({ ...diagram, callouts: diagram.callouts.map((item, i) => i === index ? { ...item, anchor } : item) })} />
        <Button variant="ghost" size="icon" aria-label={`Remove annotation ${index + 1}`} onClick={() => onChange({ ...diagram, callouts: diagram.callouts.filter((_, i) => i !== index) })}><Trash2 /></Button>
        <label className={`${label} col-span-2`}>Annotation {index + 1}
          <textarea className={`${input} min-h-20 py-2`} maxLength={1000} value={note.text} onChange={(event) => onChange({ ...diagram, callouts: diagram.callouts.map((item, i) => i === index ? { ...item, text: event.target.value } : item) })} placeholder="Explain a decision or highlight a detail" />
        </label>
      </div>)}
    </section>

    {!!issues.length && <ul aria-label="Structure needs attention" className="space-y-1 text-xs text-danger">{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="secondary" disabled={!!issues.length || loading} onClick={showPreview}><Eye />{loading ? "Preparing preview…" : "Preview prompt"}</Button>
      <span className="text-xs text-muted-foreground">No image generation or charge</span>
    </div>
    {error && <p role="alert" className="text-xs text-danger">{error}</p>}
    {preview && <section aria-label="Compiled prompt preview" className="space-y-3">
      {preview.warnings.map((warning) => <p key={warning} className="text-xs text-accent">{warning}</p>)}
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-xl border border-border bg-background-subtle p-4 font-mono text-xs leading-relaxed">{preview.text}</pre>
      <p className="text-xs text-muted-foreground">Your edit source and deck settings may add context when you generate.</p>
    </section>}
    <Button variant="primary" disabled={!!issues.length} onClick={onClose}>Use this structure</Button>
  </section>;
}
