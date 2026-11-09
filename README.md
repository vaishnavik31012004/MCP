# AI Agent Hub

An autonomous agent that plans, calls tools, and works a goal to completion —
built on real, dynamically-discovered MCP servers, with a LangGraph loop as
the brain and human-in-the-loop approval for anything risky.

You give it a goal in plain English. It figures out which tools it needs,
calls them, reads the results, decides what to do next, and keeps going until
the goal is done — pausing to ask you before it does anything irreversible
(sending an email, deleting an event).

## Why this is genuinely dynamic, not hardcoded

- **Runs entirely on free tiers.** Default `.env.example` uses Groq (free
  LLM, no card), local sentence-transformers (free embeddings, no card), and
  Nylas's free sandbox (email/calendar, no card). `utility`, `information`,
  and `location` need no keys at all. Nothing in the default setup costs
  money — swap in a paid provider later only if you want to.

- **Tool discovery.** The backend never lists "the tools" anywhere. At
  startup it launches each MCP server in `mcp_servers/` as a subprocess,
  asks it what tools it has, and builds the LLM's tool list from the answer.
  Add a new `@mcp.tool()` function to any server and restart — it's
  available to the agent with zero other code changes.
- **Risk classification.** Each tool tags its own risk with a `@risk(...)`
  decorator right next to its definition (see `mcp_servers/shared/risk.py`).
  There's no central "here's every tool and its danger level" table to keep
  in sync — the backend reads the tag back out of the tool's own docstring.
- **The agent loop is a real LangGraph `StateGraph`** (`backend/app/agent/graph.py`),
  not a hand-rolled while-loop: `agent → tools → collect → agent`, with a
  proper `interrupt()` for human-in-the-loop approval on high-risk tool
  calls, checkpointed to SQLite so a paused task survives a backend restart.
- **Memory is `langmem`**, bound into the graph as two extra tools (save,
  semantic search) — not a fake "memory server" reinventing what langmem
  already does well.

## Architecture

```
frontend/  (React + TS + Vite)  --HTTP/SSE-->  backend/  (FastAPI)
                                                    |
                                                    | stdio (subprocess per server)
                                                    v
                                              mcp_servers/
                                              ├── utility/       weather, currency, calculator, time
                                              ├── information/   web search, news, page reading
                                              ├── location/      geocoding, distance, nearby places
                                              └── nylas/         email + calendar + contacts (one API key)
```

**Backend** (`backend/app/`)
- `mcp/manager.py` — the MCP client. Launches every server in `mcp_servers/`,
  discovers tools, classifies risk, serializes calls per server (stdio is a
  single pipe).
- `agent/graph.py` — the LangGraph agent loop.
- `agent/executor.py` — drives the graph per task, turns graph state into
  events for the frontend.
- `agent/llm.py` — swap the model provider with one `.env` line (Anthropic,
  OpenAI, or any OpenAI-compatible endpoint — Mistral, Grok, Groq, etc.).
- `agent/memory.py` — langmem long-term memory. Free local embeddings
  (sentence-transformers) by default; degrades gracefully to no memory if
  the configured embeddings backend can't be set up, instead of crashing.
- `agent/state.py` — SQLite task/event log (separate from LangGraph's own
  checkpoint DB, which handles pause/resume state).
- `main.py` — FastAPI: create a task, stream its events over SSE, approve or
  reject a paused task, task history, MCP status.

**MCP servers** (`mcp_servers/`) — each is a standalone process, real APIs,
no mocked data:
- `utility` — Open-Meteo (weather/forecast), Frankfurter (currency), a safe
  AST-based calculator, IANA timezone lookups. No API keys needed.
- `information` — DuckDuckGo HTML search, page text extraction; news via
  NewsAPI.org if `NEWSAPI_KEY` is set, otherwise falls back to search.
- `location` — OpenStreetMap Nominatim (geocoding) + Overpass (nearby
  places). No API keys needed.
- `nylas` — email, calendar, and contacts through **one** Nylas API key,
  instead of separate Google/Microsoft OAuth flows. `send_email` and
  `delete_calendar_event` are HIGH risk (pause for approval);
  `create_calendar_event` is MEDIUM; everything read-only is LOW.

**Frontend** (`frontend/`) — a single-view console: task history on the
left, a live execution timeline in the center (goal → tool calls → results →
final answer, with an approval prompt inline when the agent pauses), and
connected MCP servers/tools on the right.

## Setup

### 1. Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` — everything in `.env.example` defaults to a **free tier**:

| Variable | Required for | Notes |
|---|---|---|
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | the agent to run at all | Defaults to **Groq** (free, no card — get a key at https://console.groq.com/keys) via `openai_compatible`. Swap in Anthropic/OpenAI/Mistral/etc. the same way if you have a paid key. |
| `MEMORY_EMBEDDINGS_PROVIDER` | long-term memory | Defaults to `local` — sentence-transformers running on your machine, free, no key, one-time ~90MB model download. Set to `openai` (+ `OPENAI_API_KEY`) only if you want paid embeddings instead. |
| `NYLAS_API_KEY`, `NYLAS_GRANT_ID` | email/calendar/contacts | Free sandbox (up to 5 connected accounts, no card) at https://dashboard-v3.nylas.com — plenty for personal use. |
| `NEWSAPI_KEY` | better news results | Optional, free dev tier at https://newsapi.org — `get_news` falls back to plain web search without it. |

Nothing here requires a credit card. `utility`, `information`, and `location`
need no keys at all — only `nylas` (email/calendar) and, optionally, better
news/memory quality cost you a signup, never money.

Run it:

```bash
uvicorn app.main:app --reload --port 8000
```

Check `GET /api/mcp/status` (or the console's right rail) to confirm all 4
servers connected and see every tool it discovered.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the printed localhost URL. The dev server proxies `/api` to
`http://127.0.0.1:8000` (see `vite.config.ts`).

## How a task actually runs

1. You type a goal → `POST /api/tasks` → the backend creates a task and
   starts the LangGraph loop with your goal as the first message.
2. The frontend opens `GET /api/tasks/{id}/stream` (SSE) and renders each
   `tool_call` / `tool_result` as it happens.
3. If the agent wants to call a HIGH-risk tool, the graph calls `interrupt()`
   and pauses — persisted to the checkpoint DB, so this survives a backend
   restart. The frontend shows an approve/reject prompt.
4. You approve or reject → `POST /api/tasks/{id}/decision` → the graph
   resumes from exactly where it paused.
5. The agent keeps going until it has a final answer, hits the step cap
   (`AGENT_MAX_STEPS`), or errors out — every step is logged to SQLite so
   task history survives a restart too.

## Adding a new capability

Add a function to any file in `mcp_servers/`:

```python
@mcp.tool()
@risk("LOW")  # or MEDIUM / HIGH
async def my_new_tool(some_arg: str) -> dict:
    """One-line description the LLM will see."""
    ...
```

Restart the backend. That's it — no manager code, no risk table, no frontend
change. It shows up in `/api/mcp/status` and the LLM can call it immediately.

To add a whole new server, drop a new folder in `mcp_servers/` following the
same shape as the existing ones, and add one line to the `SERVERS` dict in
`backend/app/mcp/manager.py`.
