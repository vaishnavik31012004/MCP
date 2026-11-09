import type { MCPStatus, Task, TaskEvent } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export async function createTask(goal: string): Promise<{ task_id: string }> {
  return json(
    await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal }),
    })
  );
}

export async function decideTask(taskId: string, approved: boolean): Promise<void> {
  await json(
    await fetch(`/api/tasks/${taskId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    })
  );
}

export async function listTasks(): Promise<Task[]> {
  return json(await fetch("/api/tasks"));
}

export async function getTask(taskId: string): Promise<Task & { events: TaskEvent[] }> {
  return json(await fetch(`/api/tasks/${taskId}`));
}

export async function getMcpStatus(): Promise<MCPStatus> {
  return json(await fetch("/api/mcp/status"));
}

/** Subscribes to a task's live event stream. Returns an unsubscribe function. */
export function streamTask(taskId: string, onEvent: (event: TaskEvent) => void): () => void {
  const source = new EventSource(`/api/tasks/${taskId}/stream`);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as TaskEvent);
    } catch {
      // ignore malformed frames
    }
  };
  source.onerror = () => {
    source.close();
  };
  return () => source.close();
}
