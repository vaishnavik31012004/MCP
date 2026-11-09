"""The agent's execution loop, as a compiled LangGraph `StateGraph`.

    ┌────────┐   tool_calls?    ┌───────┐  more pending?  ┌─────────┐
    │ agent  │ ───────────────► │ tools │ ───────────────►│  tools  │ (loops on itself)
    └───┬────┘                  └───┬───┘                 └────┬────┘
        │ no tool_calls              │ pending_calls empty      │
        ▼                            ▼                          │
       END                       ┌─────────┐                    │
                                  │ collect │◄───────────────────┘
                                  └────┬────┘
                                       │
                                       ▼
                                     agent  (loop back)

`agent` asks the LLM (which sees every MCP tool discovered at startup, plus
the two langmem memory tools) what to do next. `tools` executes exactly ONE
pending tool call per node invocation — deliberately, not a for-loop over all
of them — because LangGraph re-executes a node from the top when one of its
`interrupt()` calls is resumed, and a for-loop would re-run (and re-send)
every tool call before the one being approved. One call per node keeps that
re-execution side-effect-free. HIGH-risk tools call `interrupt()` and pause
the whole graph for a human decision; anything else runs immediately.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from app.mcp.manager import MCPManager

SYSTEM_PROMPT = (
    "You are an autonomous task-executing agent. You have a dynamic set of tools "
    "discovered at runtime from connected MCP servers (weather, currency, search, "
    "location, email/calendar/contacts via Nylas), plus tools to save and search "
    "your own long-term memory. Break the goal into concrete steps, call tools to "
    "make progress, read their results, and keep going until the goal is fully "
    "done. Some tools are high-risk (sending email, deleting things) and will "
    "pause for a human to approve before they run — that's expected, not an "
    "error; if rejected, tell the user and try a different approach instead of "
    "repeating the same call. When the goal is complete, reply with a plain-text "
    "final answer and do not call any more tools."
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    steps: int
    pending_calls: list[dict]
    completed: list[ToolMessage]


def build_graph(mcp_manager: MCPManager, llm, memory_tools: list[Any], max_steps: int, checkpointer):
    memory_tools_by_name = {t.name: t for t in memory_tools}
    llm_with_tools = llm.bind_tools([*mcp_manager.openai_tools(), *memory_tools])

    async def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]
        response = await llm_with_tools.ainvoke(messages)
        update: dict = {"messages": [response], "steps": state.get("steps", 0) + 1}
        if isinstance(response, AIMessage) and response.tool_calls:
            update["pending_calls"] = list(response.tool_calls)
            update["completed"] = []
        return update

    async def tools_node(state: AgentState) -> dict:
        pending = state["pending_calls"]
        call = pending[0]
        name, args, call_id = call["name"], call["args"], call["id"]

        if name in memory_tools_by_name:
            try:
                result: Any = await memory_tools_by_name[name].ainvoke(args)
            except Exception as exc:  # noqa: BLE001
                result = f"Error: {exc}"
        else:
            risk_level = mcp_manager.get_risk(name)
            if risk_level == "HIGH":
                decision = interrupt(
                    {"type": "approval_required", "tool": name, "arguments": args, "risk": risk_level}
                )
                if decision != "approve":
                    tm = ToolMessage(
                        content="Rejected by the user. Do not retry this exact call; either try a "
                        "different approach or tell the user it was skipped.",
                        tool_call_id=call_id,
                        name=name,
                    )
                    return {"pending_calls": pending[1:], "completed": state["completed"] + [tm]}
            try:
                result = await mcp_manager.call_tool(name, args)
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}

        tm = ToolMessage(content=str(result), tool_call_id=call_id, name=name)
        return {"pending_calls": pending[1:], "completed": state["completed"] + [tm]}

    def collect_node(state: AgentState) -> dict:
        return {"messages": state["completed"], "pending_calls": [], "completed": []}

    def route_from_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls and state.get("steps", 0) < max_steps:
            return "tools"
        return END

    def route_from_tools(state: AgentState) -> str:
        return "tools" if state["pending_calls"] else "collect"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("collect", collect_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_from_agent, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", route_from_tools, {"tools": "tools", "collect": "collect"})
    graph.add_edge("collect", "agent")

    return graph.compile(checkpointer=checkpointer)
