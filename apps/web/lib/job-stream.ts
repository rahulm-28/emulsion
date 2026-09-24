import type { JobOut } from "./api";

export interface JobStreamHandlers {
  onMessage?: (kind: string, message: string, seq: number) => void;
  onSnapshot?: (job: JobOut) => void;
  onDone?: (job: JobOut) => void;
  onError?: (message: string) => void;
}

/** Stream progress, falling back to authenticated polling if the connection drops. */
export function watchJobStream(jobId: string, handlers: JobStreamHandlers, loadJob: (id: string) => Promise<JobOut>, afterSeq = -1): () => void {
  const source = new EventSource(`/v1/jobs/${jobId}/events`);
  let active = true;
  let polling = false;
  let failures = 0;
  let lastSeq = afterSeq;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const stop = () => {
    active = false;
    source.close();
    clearTimeout(timer);
  };
  const finish = (job: JobOut) => {
    if (!active) return;
    stop();
    handlers.onDone?.(job);
  };
  const poll = async () => {
    if (!active) return;
    try {
      const job = await loadJob(jobId);
      if (!active) return;
      failures = 0;
      if (job.status === "succeeded" || job.status === "failed") {
        finish(job);
        return;
      }
      handlers.onSnapshot?.(job);
    } catch {
      if (!active) return;
      failures += 1;
      if (failures >= 3) {
        stop();
        handlers.onError?.("Could not reconnect. Your request is saved; reopen this conversation to check its progress.");
        return;
      }
    }
    timer = setTimeout(poll, 1500 * Math.max(1, failures));
  };
  const fallback = () => {
    if (!active || polling) return;
    polling = true;
    source.close();
    clearTimeout(timer);
    void poll();
  };
  const watchdog = () => {
    clearTimeout(timer);
    // A silent connection must not strand the composer indefinitely.
    timer = setTimeout(fallback, 20000);
  };
  const relay = (kind: string) => (event: Event) => {
    if (!active || polling) return;
    try {
      const data = JSON.parse((event as MessageEvent).data);
      watchdog();
      if (typeof data.seq === "number" && data.seq > lastSeq) {
        lastSeq = data.seq;
        handlers.onMessage?.(kind, data.message ?? "", data.seq);
      }
    } catch { /* Transport errors go through the fallback below. */ }
  };
  for (const kind of ["status", "progress", "warning", "error"]) {
    source.addEventListener(kind, relay(kind));
  }
  source.addEventListener("done", (event) => {
    if (!active || polling) return;
    try { finish(JSON.parse((event as MessageEvent).data) as JobOut); }
    catch { fallback(); }
  });
  source.addEventListener("timeout", fallback);
  source.onerror = fallback;
  watchdog();
  return stop;
}
