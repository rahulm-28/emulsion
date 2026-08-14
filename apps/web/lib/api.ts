/**
 * Client for the Emulsion API.
 *
 * Same-origin throughout — next.config.mjs rewrites /v1/* to the API, exactly as Front
 * Door does in production. There is deliberately no configurable base URL here.
 */

import { authHeaders } from "./auth";

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface Region {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface ImageOut {
  id: string;
  job_id: string | null;
  parent_id: string | null;
  /** Archival original — can be 13 MB. Prefer viewer_url / gallery_url for display. */
  url: string;
  viewer_url: string;
  gallery_url: string;
  width: number;
  height: number;
  size_bytes: number;
  model_id: string;
  prompt: string;
  created_at: string;
}

export interface DroppedPart {
  kind: string;
  reason: string;
}

export interface JobEventOut {
  seq: number;
  kind: string;
  message: string;
  created_at: string;
}

export interface JobOut {
  id: string;
  session_id: string | null;
  status: JobStatus;
  model_id: string;
  prompt: string;
  size: string;
  n: number;
  parent_image_id: string | null;
  region: Region | null;
  error: string | null;
  dropped_parts: DroppedPart[];
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  images: ImageOut[];
  events: JobEventOut[];
}

export interface SessionOut {
  id: string;
  title: string;
  model_id: string;
  job_count: number;
  image_count: number;
  style_id: string | null;
  link_consistency: boolean;
  cost_usd: number;
  thumbnail_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface StyleIn {
  name: string;
  legend?: Record<string, string>;
  rules?: string[];
  style_words?: string[];
  layout?: string;
}

export interface StyleOut {
  id: string;
  name: string;
  legend: Record<string, string>;
  rules: string[];
  style_words: string[];
  layout: string;
  created_at: string;
  updated_at: string;
}

export interface SuggestionOut {
  text: string;
  occurrences: number;
  examples: string[];
}

export interface ModelOut {
  id: string;
  provider: string;
  sizes: string[];
  max_n_per_request: number;
  mask_support: string;
  edit_full_regen: boolean;
  unsupported_params: string[];
  approx_rpm: number;
}

export interface HealthOut {
  status: string;
  adapter: string;
  queue_depth: number;
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try {
      detail = JSON.parse(body).detail ?? body;
    } catch {
      /* keep the raw body */
    }
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

const noStore: RequestInit = { cache: "no-store" };

/** GET with the session token attached when auth is enabled. */
async function authedGet(path: string): Promise<Response> {
  return fetch(path, { ...noStore, headers: await authHeaders() });
}

async function jsonHeaders(): Promise<Record<string, string>> {
  return { "Content-Type": "application/json", ...(await authHeaders()) };
}

export async function getHealth(): Promise<HealthOut> {
  return json(await authedGet("/health"));
}

export async function listModels(): Promise<ModelOut[]> {
  return json(await authedGet("/v1/models"));
}

export async function getJob(id: string): Promise<JobOut> {
  return json(await authedGet(`/v1/jobs/${id}`));
}

export async function listSessions(): Promise<SessionOut[]> {
  return json(await authedGet("/v1/sessions"));
}

export async function listSessionJobs(sessionId: string): Promise<JobOut[]> {
  return json(await authedGet(`/v1/sessions/${sessionId}/jobs`));
}

export async function patchSession(
  id: string,
  patch: { title?: string; style_id?: string | null; link_consistency?: boolean },
): Promise<SessionOut> {
  return json(
    await fetch(`/v1/sessions/${id}`, {
      method: "PATCH",
      headers: await jsonHeaders(),
      body: JSON.stringify(patch),
    }),
  );
}

export async function renameSession(id: string, title: string): Promise<SessionOut> {
  return patchSession(id, { title });
}

export async function listStyles(): Promise<StyleOut[]> {
  return json(await authedGet("/v1/styles"));
}

export async function listSuggestions(): Promise<SuggestionOut[]> {
  return json(await authedGet("/v1/styles/suggestions?min_occurrences=3"));
}

export async function createStyle(body: StyleIn): Promise<StyleOut> {
  return json(
    await fetch("/v1/styles", {
      method: "POST",
      headers: await jsonHeaders(),
      body: JSON.stringify(body),
    }),
  );
}

export async function updateStyle(id: string, body: StyleIn): Promise<StyleOut> {
  return json(
    await fetch(`/v1/styles/${id}`, {
      method: "PATCH",
      headers: await jsonHeaders(),
      body: JSON.stringify(body),
    }),
  );
}

export async function deleteStyle(id: string): Promise<void> {
  const response = await fetch(`/v1/styles/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`could not delete style (${response.status})`);
  }
}

export async function deleteSession(id: string): Promise<void> {
  const response = await fetch(`/v1/sessions/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`could not delete session (${response.status})`);
  }
}

export async function listImages(): Promise<ImageOut[]> {
  return json(await authedGet("/v1/images?limit=60"));
}

export async function getLineage(imageId: string): Promise<ImageOut[]> {
  return json(await authedGet(`/v1/images/${imageId}/lineage`));
}

export interface CreateJobBody {
  prompt: string;
  model_id: string;
  size: string;
  n: number;
  parent_image_id?: string | null;
  session_id?: string | null;
  region?: Region | null;
}

export async function createJob(body: CreateJobBody): Promise<JobOut> {
  return json(
    await fetch("/v1/jobs", {
      method: "POST",
      headers: {
        ...(await jsonHeaders()),
        // Invariant 8. A double-submitted retry must not become a double charge, so
        // the key is generated per submission attempt, not per render.
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify(body),
    }),
  );
}

export interface ExportRequest {
  format: "png" | "webp" | "jpeg";
  transparent?: boolean;
  scale?: number;
  quality?: number;
}

export interface ExportOut {
  url: string;
  width: number;
  height: number;
  content_type: string;
  has_alpha: boolean;
  background_uniform: boolean;
  size_bytes: number;
}

export async function exportImage(
  imageId: string,
  body: ExportRequest,
): Promise<ExportOut> {
  return json(
    await fetch(`/v1/images/${imageId}/export`, {
      method: "POST",
      headers: await jsonHeaders(),
      body: JSON.stringify(body),
    }),
  );
}

export interface JobStreamHandlers {
  onMessage?: (kind: string, message: string) => void;
  onDone?: (job: JobOut) => void;
  onError?: (message: string) => void;
}

/**
 * Subscribe to a job's progress. Returns an unsubscribe function.
 *
 * The server closes the stream once the job is terminal, so there is nothing to poll.
 */
export function streamJob(jobId: string, handlers: JobStreamHandlers): () => void {
  const source = new EventSource(`/v1/jobs/${jobId}/events`);

  const relay = (kind: string) => (event: Event) => {
    try {
      handlers.onMessage?.(kind, JSON.parse((event as MessageEvent).data).message ?? "");
    } catch {
      /* a malformed frame is not worth breaking the stream over */
    }
  };

  source.addEventListener("status", relay("status"));
  source.addEventListener("progress", relay("progress"));
  source.addEventListener("warning", relay("warning"));
  source.addEventListener("error", relay("error"));

  source.addEventListener("done", (event) => {
    try {
      handlers.onDone?.(JSON.parse((event as MessageEvent).data) as JobOut);
    } catch (err) {
      handlers.onError?.(String(err));
    }
    source.close();
  });

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      handlers.onError?.("connection to the job stream was lost");
    }
  };

  return () => source.close();
}
