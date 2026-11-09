import type { Task, TaskEvent } from "../types";

function ToolCallRow({ payload }: { payload: Record<string, unknown> }) {
  return (
    <div className="event">
      <div className="event-marker">call</div>
      <div className="event-body">
        <span className="event-tool-name">{String(payload.tool)}</span>
        {payload.arguments != null && Object.keys(payload.arguments as object).length > 0 && (
          <div className="event-args">{JSON.stringify(payload.arguments, null, 2)}</div>
        )}
      </div>
    </div>
  );
}

function ToolResultRow({ payload }: { payload: Record<string, unknown> }) {
  return (
    <div className="event">
      <div className="event-marker">result</div>
      <div className="event-body">
        <span className="event-tool-name">{String(payload.tool)}</span>
        <div className="event-result">{String(payload.result)}</div>
      </div>
    </div>
  );
}

export default function Timeline({ task, events }: { task: Task | null; events: TaskEvent[] }) {
  if (!task) {
    return (
      <div className="timeline">
        <p className="empty-state">
          Describe a goal below and the agent will plan, call tools, and work through it step by
          step — high-risk actions (like sending email) will pause here for your approval.
        </p>
      </div>
    );
  }

  return (
    <div className="timeline">
      <div className="event">
        <div className="event-marker">goal</div>
        <div className="event-body event-goal">{task.goal}</div>
      </div>
      {events.map((event, i) => {
        switch (event.type) {
          case "tool_call":
            return <ToolCallRow key={i} payload={event.payload} />;
          case "tool_result":
            return <ToolResultRow key={i} payload={event.payload} />;
          case "final_answer":
            return (
              <div className="event" key={i}>
                <div className="event-marker">answer</div>
                <div className="event-body event-final">{String(event.payload.content)}</div>
              </div>
            );
          case "error":
            return (
              <div className="event" key={i}>
                <div className="event-marker">error</div>
                <div className="event-body event-error">{String(event.payload.error)}</div>
              </div>
            );
          default:
            return null;
        }
      })}
    </div>
  );
}
