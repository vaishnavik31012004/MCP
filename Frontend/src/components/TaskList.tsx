import type { Task } from "../types";

function statusLabel(status: Task["status"]): string {
  switch (status) {
    case "waiting_approval":
      return "needs approval";
    default:
      return status;
  }
}

export default function TaskList({
  tasks,
  activeTaskId,
  onSelect,
  onNew,
}: {
  tasks: Task[];
  activeTaskId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="rail-left">
      <button className="new-task-btn" onClick={onNew}>
        + New task
      </button>
      <p className="rail-heading">TASKS</p>
      {tasks.length === 0 && <p className="empty-state">No tasks yet.</p>}
      {tasks.map((task) => (
        <button
          key={task.id}
          className={`task-item ${task.id === activeTaskId ? "active" : ""}`}
          onClick={() => onSelect(task.id)}
        >
          <span className="goal">{task.goal}</span>
          <span className="meta">
            <span className={`dot ${task.status}`} />
            {statusLabel(task.status)}
          </span>
        </button>
      ))}
    </div>
  );
}
