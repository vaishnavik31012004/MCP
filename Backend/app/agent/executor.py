"""Drives one compiled graph per app instance across many tasks (threads).

Each task gets its own LangGraph `thread_id`, so its checkpointed state
(messages, pending tool calls, pause point) lives independently of every
other task. `run` and `resume` are async generators of plain dicts the
FastAPI layer turns straight into Server-Sent Events.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.agent.state import TaskStore

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, graph, task_store: TaskStore):
        self.graph = graph
        self.task_store = task_store
        # How many messages of each task's thread we've already turned into
        # events. `stream_mode="values"` re-sends the *whole* messages list
        # on every super-step, so without this we'd re-emit the same
        # tool_call/tool_result every time an adjacent field (like
        # pending_calls) changes but messages didn't grow.
        self._seen_message_counts: dict[str, int] = {}

    def _config(self, task_id: str) -> dict:
        return {"configurable": {"thread_id": task_id}}

    async def run(self, task_id: str, goal: str) -> AsyncIterator[dict[str, Any]]:
        self._seen_message_counts[task_id] = 0
        initial_state = {
            "messages": [HumanMessage(content=goal)],
            "steps": 0,
            "pending_calls": [],
            "completed": [],
        }
        async for event in self._drive(task_id, initial_state):
            yield event

    async def resume(self, task_id: str, approved: bool) -> AsyncIterator[dict[str, Any]]:
        command = Command(resume="approve" if approved else "reject")
        async for event in self._drive(task_id, command):
            yield event

    async def _drive(self, task_id: str, graph_input: Any) -> AsyncIterator[dict[str, Any]]:
        config = self._config(task_id)
        seen = self._seen_message_counts.get(task_id, 0)
        try:
            async for chunk in self.graph.astream(graph_input, config=config, stream_mode="values"):
                messages = chunk.get("messages", [])
                if len(messages) <= seen:
                    continue
                for message in messages[seen:]:
                    for event in self._message_to_events(task_id, message):
                        yield event
                seen = len(messages)
            self._seen_message_counts[task_id] = seen

            # The astream loop above ends both when the graph finishes AND
            # when it pauses on an interrupt — those look identical from the
            # stream itself in this LangGraph version, so the only reliable
            # way to tell them apart is to check the persisted state after
            # the loop: a pending interrupt shows up on the next task there.
            snapshot = await self.graph.aget_state(config)
            pending_interrupts = [i for task in snapshot.tasks for i in task.interrupts]
            if pending_interrupts:
                payload = pending_interrupts[0].value
                self.task_store.update_status(task_id, "waiting_approval")
                self.task_store.add_event(task_id, "approval_required", payload)
                yield {"type": "approval_required", "payload": payload}

        except Exception as exc:  # noqa: BLE001
            logger.exception("Task %s failed", task_id)
            payload = {"error": str(exc)}
            self.task_store.add_event(task_id, "error", payload)
            self.task_store.update_status(task_id, "failed", result=payload)
            yield {"type": "error", "payload": payload}

    def _message_to_events(self, task_id: str, message) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        if isinstance(message, AIMessage) and message.tool_calls:
            for call in message.tool_calls:
                payload = {"tool": call["name"], "arguments": call["args"]}
                self.task_store.add_event(task_id, "tool_call", payload)
                events.append({"type": "tool_call", "payload": payload})
        elif isinstance(message, ToolMessage):
            payload = {"tool": message.name, "result": message.content}
            self.task_store.add_event(task_id, "tool_result", payload)
            events.append({"type": "tool_result", "payload": payload})
        elif isinstance(message, AIMessage) and not message.tool_calls:
            payload = {"content": message.content}
            self.task_store.add_event(task_id, "final_answer", payload)
            self.task_store.update_status(task_id, "completed", result=payload)
            events.append({"type": "final_answer", "payload": payload})

        return events
