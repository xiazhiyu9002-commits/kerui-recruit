import type { TaskStatus } from "../App";

const terminal = new Set(["SUCCESS", "FAILED", "DEAD_LETTER", "CANCELLED", "PAUSED"]);

function pause(milliseconds: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException("Stopped", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, milliseconds);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** Track durable work until it finishes, is paused, or the owning UI goes away. */
export async function waitForTask(
  getTask: () => Promise<TaskStatus>,
  onStatus: (task: TaskStatus) => void,
  options: { signal: AbortSignal; interval?: number; onError?: (error: unknown) => void },
): Promise<TaskStatus> {
  while (true) {
    options.signal.throwIfAborted();
    try {
      const task = await getTask();
      options.signal.throwIfAborted();
      onStatus(task);
      if (terminal.has(task.status)) return task;
    } catch (error) {
      options.signal.throwIfAborted();
      options.onError?.(error);
    }
    await pause(options.interval ?? 1500, options.signal);
  }
}
