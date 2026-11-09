export type TaskStatus = "running" | "waiting_approval" | "completed" | "failed" | "cancelled";

export interface Task {
  id: string;
  goal: string;
  status: TaskStatus;
  result: { content?: string; error?: string } | null;
  created_at: string;
  updated_at: string;
}

export interface TaskEvent {
  type: "tool_call" | "tool_result" | "approval_required" | "final_answer" | "error" | "done";
  payload: Record<string, unknown>;
  created_at?: string;
}

export interface ToolInfo {
  name: string;
  server: string;
  risk: "LOW" | "MEDIUM" | "HIGH";
  description: string;
}

export interface MCPStatus {
  servers_connected: string[];
  servers_total: number;
  errors: Record<string, string>;
  tools: ToolInfo[];
}
