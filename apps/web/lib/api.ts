/**
 * Client for the Emulsion API.
 *
 * Same-origin throughout — next.config.mjs rewrites /v1/* to the API, exactly as Front
 * Door does in production. There is deliberately no configurable base URL here.
 */

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface ImageOut {
  id: string;
  job_id: string | null;
  parent_id: string | null;
  url: string;
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
  cost_usd: number;
  thumbnail_url: string | null;
  created_at: string;
  updated_at: string;
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

export async function getHealth(): Promise<HealthOut> {
  return json(await fetch("/health", noStore));
}

export async function listModels(): Promise<ModelOut[]> {
  return json(await fetch("/v1/models", noStore));
}

export async function getJob(id: string): Promise<JobOut> {
  return json(await fetch(`/v1/jobs/${id}`, noStore));
}

export async function listSessions(): Promise<SessionOut[]> {
  return json(await fetch("/v1/sessions", noStore));
}

export async function listSessionJobs(sessionId: string): Promise<JobOut[]> {
  return json(await fetch(`/v1/sessions/${sessionId}/jobs`, noStore));
}

export async function renameSession(id: string, title: string): Promise<SessionOut> {
  return json(
    await fetch(`/v1/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function deleteSession(id: string): Promise<void> {
  const response = await fetch(`/v1/sessions/${id}`, { method: "DELETE" });
  if (!response.ok && response.status !== 204) {
    throw new Error(`could not delete session (${response.status})`);
  }
}

export async function listImages(): Promise<ImageOut[]> {
  return json(await fetch("/v1/images?limit=60", noStore));
}

export async function getLineage(imageId: string): Promise<ImageOut[]> {
  return json(await fetch(`/v1/images/${imageId}/lineage`, noStore));
}

export interface CreateJobBody {
  prompt: string;
  model_id: string;
  size: string;
  n: number;
  parent_image_id?: string | null;
  session_id?: string | null;
}

export async function createJob(body: CreateJobBody): Promise<JobOut> {
  return json(
    await fetch("/v1/jobs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Invariant 8. A double-submitted retry must not become a double charge, so
        // the key is generated per submission attempt, not per render.
        "Idempotency-Key": crypto.randomUUID(),
      },
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
