import assert from "node:assert/strict";
import { test } from "node:test";
import { watchJobStream } from "../lib/job-stream.ts";

class Source {
  static latest;
  listeners = new Map();
  closed = false;
  constructor() { Source.latest = this; }
  addEventListener(kind, handler) { this.listeners.set(kind, handler); }
  emit(kind, data) { this.listeners.get(kind)?.({ data: JSON.stringify(data) }); }
  close() { this.closed = true; }
}
const settle = () => new Promise((resolve) => setImmediate(resolve));
function setup(t) { t.mock.method(globalThis, "EventSource", Source); }
// Node has no browser EventSource. Keep the mock local to this test process.
globalThis.EventSource = Source;

test("stream replay skips saved events and completes exactly once", (t) => {
  setup(t);
  const messages = [], completed = [];
  const stop = watchJobStream("job", { onMessage: (...args) => messages.push(args), onDone: (job) => completed.push(job) }, () => assert.fail("unexpected polling"), 4);
  Source.latest.emit("status", { seq: 3, message: "already seen" });
  Source.latest.emit("progress", { seq: 5, message: "rendering" });
  Source.latest.emit("progress", { seq: 5, message: "rendering" });
  Source.latest.emit("done", { status: "succeeded" });
  Source.latest.emit("done", { status: "succeeded" });
  assert.deepEqual(messages, [["progress", "rendering", 5]]);
  assert.equal(completed.length, 1);
  assert.equal(Source.latest.closed, true);
  stop();
});

test("connection loss recovers the terminal job using authenticated loader", async (t) => {
  setup(t);
  const completed = [];
  const stop = watchJobStream("job", { onDone: (job) => completed.push(job) }, async (id) => {
    assert.equal(id, "job");
    return { status: "succeeded", images: [{ id: "result" }] };
  });
  Source.latest.onerror();
  await settle();
  assert.equal(completed[0].images[0].id, "result");
  assert.equal(Source.latest.closed, true);
  stop();
});

test("navigation suppresses a late polling result", async (t) => {
  setup(t);
  let resolve;
  const stop = watchJobStream("old", { onDone: () => assert.fail("stale result") }, () => new Promise((r) => { resolve = r; }));
  Source.latest.onerror();
  stop();
  resolve({ status: "succeeded" });
  await settle();
});

test("a silent stream falls back and keeps checking until completion", async (t) => {
  setup(t);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let reads = 0;
  const snapshots = [], completed = [];
  const stop = watchJobStream("job", { onSnapshot: (job) => snapshots.push(job), onDone: (job) => completed.push(job) }, async () => ({ status: ++reads === 1 ? "running" : "succeeded" }));
  t.mock.timers.tick(20000);
  await settle();
  assert.equal(snapshots[0].status, "running");
  // A buffered frame from the closed stream must not cancel the next poll.
  Source.latest.emit("progress", { seq: 8, message: "late frame" });
  t.mock.timers.tick(1500);
  await settle();
  assert.equal(completed[0].status, "succeeded");
  stop();
});

test("repeated recovery failures release the UI with a useful message", async (t) => {
  setup(t);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const errors = [];
  const stop = watchJobStream("job", { onError: (message) => errors.push(message) }, async () => { throw new Error("offline"); });
  Source.latest.onerror();
  await settle();
  t.mock.timers.tick(1500);
  await settle();
  t.mock.timers.tick(3000);
  await settle();
  assert.match(errors[0], /reopen this conversation/);
  assert.equal(Source.latest.closed, true);
  stop();
});
