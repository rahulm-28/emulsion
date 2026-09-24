export interface DiagramComponent {
  name: string;
  layer: string;
  role: string;
  items: string[];
  note: string;
  emphasis: "dominant" | "normal" | "aside";
}

export interface DiagramConnection {
  source: string;
  target: string;
  label: string;
  bidirectional: boolean;
  weight: "primary" | "secondary";
}

export interface DiagramSpec {
  title: string;
  key_message: string;
  layout: string;
  legend: Record<string, string>;
  components: DiagramComponent[];
  connections: DiagramConnection[];
  callouts: { anchor: string; text: string }[];
  consistency_with: string;
}

export function emptyDiagram(): DiagramSpec {
  return {
    title: "", key_message: "", layout: "", legend: {},
    components: [], connections: [], callouts: [], consistency_with: "",
  };
}

export function diagramIssues(diagram: DiagramSpec): string[] {
  const issues: string[] = [];
  const names = diagram.components.map((component) => component.name.trim());
  if (!diagram.title.trim()) issues.push("Give the diagram a title.");
  if (names.some((name) => !name)) issues.push("Give every component a name.");
  if (new Set(names).size !== names.length) issues.push("Component names must be unique.");
  if (diagram.connections.some((link) => !names.includes(link.source.trim()) || !names.includes(link.target.trim()) || !link.source.trim() || !link.target.trim())) {
    issues.push("Choose both components for every connection.");
  }
  if (diagram.callouts.some((note) => !note.anchor.trim() || !names.includes(note.anchor.trim()) || !note.text.trim())) {
    issues.push("Give every annotation a component and some text.");
  }
  return issues;
}
