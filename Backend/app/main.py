from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.executor import AgentRuntime
from app.agent.graph import build_graph
from app.agent.llm import build_llm
from app.agent.memory import build_memory
from app.agent.state import TaskStore
from app.config import get_settings
from app.mcp.manager import MCPManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


class AppState:
    mcp_manager: MCPManager
    runtime: AgentRuntime
    task_store: TaskStore
    queues: dict[str, asyncio.Queue]
    checkpointer_conn: aiosqlite.Connection


state = AppState()
state.queues = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    state.task_store = TaskStore(settings.database_path)

    state.mcp_manager = MCPManager(python_executable=settings.python_executable)
    await state.mcp_manager.connect_all()

    llm = build_llm(settings)
    _memory_store, memory_tools = build_memory(settings)

    checkpoint_path = settings.database_path.replace(".db", "_checkpoints.db")
    state.checkpointer_conn = await aiosqlite.connect(checkpoint_path)
    checkpointer = AsyncSqliteSaver(state.checkpointer_conn)
    await checkpointer.setup()

    graph = build_graph(
        mcp_manager=state.mcp_manager,
        llm=llm,
        memory_tools=memory_tools,
        max_steps=settings.agent_max_steps,
        checkpointer=checkpointer,
    )
    state.runtime = AgentRuntime(graph=graph, task_store=state.task_store)

    logger.info("Startup complete: %s", state.mcp_manager.status())
    yield

    await state.mcp_manager.close()
    await state.checkpointer_conn.close()


app = FastAPI(title="AI Agent Hub", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateTaskRequest(BaseModel):
    goal: str


def _get_queue(task_id: str) -> asyncio.Queue:
    return state.queues.setdefault(task_id, asyncio.Queue())


async def _pump(task_id: str, agen) -> None:
    """Drains a runtime event generator into the task's SSE queue."""
    queue = _get_queue(task_id)
    async for event in agen:
        await queue.put(event)
    task = state.task_store.get_task(task_id)
    if task and task["status"] in ("completed", "failed"):
        await queue.put({"type": "done"})


@app.post("/api/tasks")
async def create_task(body: CreateTaskRequest):
    task_id = state.task_store.create_task(body.goal)
    asyncio.create_task(_pump(task_id, state.runtime.run(task_id, body.goal)))
    return {"task_id": task_id}


@app.get("/api/tasks/{task_id}/stream")
async def stream_task(task_id: str):
    if state.task_store.get_task(task_id) is None:
        raise HTTPException(404, "Unknown task")

    async def event_source():
        queue = _get_queue(task_id)
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("final_answer", "error", "done"):
                break

    return StreamingResponse(event_source(), media_type="text/event-stream")


class ApprovalRequest(BaseModel):
    approved: bool


@app.post("/api/tasks/{task_id}/decision")
async def decide_task(task_id: str, body: ApprovalRequest):
    task = state.task_store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Unknown task")
    if task["status"] != "waiting_approval":
        raise HTTPException(409, f"Task is not waiting for approval (status: {task['status']}).")
    state.task_store.update_status(task_id, "running")
    asyncio.create_task(_pump(task_id, state.runtime.resume(task_id, body.approved)))
    return {"status": "resumed"}


@app.get("/api/tasks")
async def list_tasks(limit: int = 50):
    return state.task_store.list_tasks(limit=limit)


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = state.task_store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Unknown task")
    return {**task, "events": state.task_store.get_events(task_id)}


@app.get("/api/mcp/status")
async def mcp_status():
    return state.mcp_manager.status()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
