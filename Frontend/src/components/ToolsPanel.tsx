import type { MCPStatus } from "../types";

export default function ToolsPanel({ status }: { status: MCPStatus | null }) {
  if (!status) {
    return (
      <div className="rail-right">
        <p className="rail-heading">MCP SERVERS</p>
        <p className="empty-state">Loading…</p>
      </div>
    );
  }

  const byServer = new Map<string, typeof status.tools>();
  for (const tool of status.tools) {
    const list = byServer.get(tool.server) ?? [];
    list.push(tool);
    byServer.set(tool.server, list);
  }

  const allServers = new Set([...status.servers_connected, ...Object.keys(status.errors)]);

  return (
    <div className="rail-right">
      <p className="rail-heading">
        MCP SERVERS ({status.servers_connected.length}/{status.servers_total})
      </p>
      {[...allServers].sort().map((server) => (
        <div className="server-group" key={server}>
          <div className="server-name">
            <span className={`dot ${status.errors[server] ? "high" : "low"}`} />
            {server}
          </div>
          {status.errors[server] && <p className="server-error">{status.errors[server]}</p>}
          {(byServer.get(server) ?? []).map((tool) => (
            <div className="tool-row" key={tool.name}>
              <span className={`dot ${tool.risk.toLowerCase()}`} />
              <span className="name">{tool.name.split("__")[1]}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
