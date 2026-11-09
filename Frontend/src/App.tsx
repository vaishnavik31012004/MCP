import { useCallback, useEffect, useRef, useState } from "react";
import TaskList from "./components/TaskList";
import ToolsPanel from "./components/ToolsPanel";
import Timeline from "./components/Timeline";
import ApprovalBar from "./components/ApprovalBar";
import GoalForm from "./components/GoalForm";
import { createTask, decideTask, getMcpStatus, getTask, listTasks, streamTask } from "./api";
import type { MCPStatus, Task, TaskEvent } from "./types";

interface ApprovalPayload {
  tool: string;
  arguments: Record<string, unknown>;
  risk: string;
}

export default function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [mcpStatus, setMcpStatus] = useState<MCPStatus | null>(null);
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [pendingApproval, setPendingApproval] = useState<ApprovalPayload | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const unsubscribeRef = useRef<() => void>();

  const refreshTasks = useCallback(() => {
    listTasks().then(setTasks).catch(console.error);
  }, []);

  useEffect(() => {
    refreshTasks();
    getMcpStatus().then(setMcpStatus).catch(console.error);
    const interval = setInterval(() => getMcpStatus().then(setMcpStatus).catch(() => {}), 15000);
    return () => clearInterval(interval);
  }, [refreshTasks]);

  const attachStream = useCallback(
    (taskId: string) => {
      unsubscribeRef.current?.();
      unsubscribeRef.current = streamTask(taskId, (event) => {
        setEvents((prev) => [...prev, event]);
        if (event.type === "approval_required") {
          setPendingApproval(event.payload as unknown as ApprovalPayload);
        }
        if (event.type === "final_answer" || event.type === "error") {
          setPendingApproval(null);
        }
        if (event.type !== "tool_call" && event.type !== "tool_result") {
          refreshTasks();
        }
      });
    },
    [refreshTasks]
  );

  useEffect(() => () => unsubscribeRef.current?.(), []);

  async function handleNewTask() {
    unsubscribeRef.current?.();
    setActiveTask(null);
    setEvents([]);
    setPendingApproval(null);
  }

  async function handleSubmitGoal(goal: string) {
    setSubmitting(true);
    try {
      const { task_id } = await createTask(goal);
      setEvents([]);
      setPendingApproval(null);
      setActiveTask({
        id: task_id,
        goal,
        status: "running",
        result: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      attachStream(task_id);
      refreshTasks();
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSelectTask(taskId: string) {
    unsubscribeRef.current?.();
    setPendingApproval(null);
    try {
      const detail = await getTask(taskId);
      setActiveTask(detail);
      setEvents(detail.events);
      const lastApproval = [...detail.events].reverse().find((e) => e.type === "approval_required");
      if (detail.status === "waiting_approval" && lastApproval) {
        setPendingApproval(lastApproval.payload as unknown as ApprovalPayload);
      }
      if (detail.status === "running" || detail.status === "waiting_approval") {
        attachStream(taskId);
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function handleDecision(approved: boolean) {
    if (!activeTask) return;
    setPendingApproval(null);
    try {
      await decideTask(activeTask.id, approved);
    } catch (err) {
      console.error(err);
    }
  }

  const connectedCount = mcpStatus?.servers_connected.length ?? 0;
  const totalCount = mcpStatus?.servers_total ?? 0;

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>AGENT CONSOLE</h1>
          <span className="subtitle">autonomous task execution over MCP</span>
        </div>
        <div className="header-status">
          {connectedCount}/{totalCount} mcp servers online
        </div>
      </header>
      <div className="layout">
        <TaskList
          tasks={tasks}
          activeTaskId={activeTask?.id ?? null}
          onSelect={handleSelectTask}
          onNew={handleNewTask}
        />
        <div className="center">
          <Timeline task={activeTask} events={events} />
          {pendingApproval && <ApprovalBar payload={pendingApproval} onDecide={handleDecision} />}
          <GoalForm onSubmit={handleSubmitGoal} disabled={submitting || !!pendingApproval} />
        </div>
        <ToolsPanel status={mcpStatus} />
      </div>
    </div>
  );
}
