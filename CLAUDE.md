# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working Agreements

- The user runs `git add`/`commit`/`push` themselves — never run them, and don't ask.
- Work directly on `main` — don't create separate branches.
- Check the docs under `docs/` first for anything design-related.
- Don't edit source directly on request — propose the change and get the user's sign-off first.

## Project

Data Access Copilot — a NL2SQL agent that turns natural-language questions into validated, executed SQL via a LangGraph pipeline: schema linking → SQL generation → validation → execution. A generic connector builds a RAG index over any Postgres schema given just connection info.

## Commands

### Infra

```bash
docker compose up -d   # postgres (target domain DB, port 5432), qdrant (6333), app-db (port 5433, app's own operational DB)
```

### Backend (`server/`)

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/init_app_db.py                                   # apply app-db schema (runs, domain_connections)
python scripts/register_domain.py --name <domain> --host localhost --port 5432 \
  --dbname <dbname> --user postgres --password postgres --schemas <schema> --activate

uvicorn app.main:app --reload --port 8000
```

Useful scripts:
- `scripts/test_connection.py --domain <name>` — verify DB connection + schema introspection
- `scripts/run_graph_cli.py --domain <name> --question "..."` — invoke the graph directly (auto mode, no interrupts), useful for debugging the pipeline without the API/UI
- `scripts/seed_few_shot.py` — seed few-shot examples into Qdrant
- `eval/token_cost_comparison.py --domain <name> --compare schema_rag_mode=rag,full_dump` — KPI runner comparing tag variants (token cost, latency, success rate) over a benchmark query set; the source of any "this change improved performance/cost" claim
- `eval/execution_accuracy.py` — accuracy eval against a golden set

There is no pytest suite; correctness is checked via the scripts/eval runners above against real Postgres/Qdrant infra.

### Frontend (`client/`)

```bash
cd client
npm install
npm run dev       # http://localhost:5173
npm run build     # tsc -b && vite build
npm run lint      # oxlint
```

### Health checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/domain/status
```

## Architecture

### Domain model: one active target DB at a time

The agent operates against exactly one "domain" (a target Postgres schema) at a time, enforced by a DB unique constraint on `domain_connections.is_active`. Domain connection info (host/port/credentials, Fernet-encrypted password) lives in the app-db `domain_connections` table, not `.env` — it's meant to be entered by a user at runtime via `scripts/register_domain.py`, since in production it comes from a UI form. `.env` only holds infra-level config (LLM gateway, app-db location, `APP_SECRET_KEY` for encryption).

Each domain also has a static "domain pack" under `server/domains/<name>/`: few-shot examples, prompt fragments (YAML), benchmark queries. `app/domain/loader.py`'s `get_domain()` joins the DB row (connection) with the domain pack directory (`DomainConfig`). Actual schema introspection happens lazily via `app/sql/schema_provider.py`, not at load time.

Two separate Postgres instances matter: the **target domain DB** (whatever the agent queries — swappable) and **app-db** (fixed, holds run registry + LangGraph checkpoints + domain_connections; survives domain switches).

### LangGraph pipeline (`app/graph/build.py`)

```
START → intent → schema_linking → schema_review → sql_generation
sql_generation --(VALUE_UNCONFIRMED, retry_count<max_retries)--> sql_generation
sql_generation --(sql ready)--> sql_review → validation
validation --(sql review on, failed)--> sql_review
validation --(sql review off, citation/anchor fail, retries left)--> sql_generation
validation --(sql review off, SqlValidator fail or retries exhausted)--> END
validation --(all pass)--> execution
execution --(sql review on, failed)--> sql_review
execution --(sql review off, timeout/exec error/zero-row, retries left)--> sql_generation
execution --(sql review off, success or retries exhausted)--> END
```

State is a single `TypedDict` (`app/graph/state.py`, `GraphState`) threaded through every node — grep it before adding a node to see what's already available downstream.

Key routing subtlety: when `review_config.sql` is on and validation/execution fails, the graph routes back to `sql_review` (human), **not** `sql_generation` (auto-regenerate) — this is deliberate so an auto-retry never silently overwrites SQL a human already approved. That path repeats until a human fixes/re-approves it, independent of `max_retries`.

### Human-in-the-loop via interrupt/resume

`schema_review` and `sql_review` are no-op passthrough nodes when `review_config.{schema,sql}` are both off — the graph runs to completion in one `graph.invoke()`, and this path works fine even with `checkpointer=None` (used by `run_graph_cli.py`, `eval/token_cost_comparison.py`).

When a review flag is on, that node calls `interrupt()`, which requires a `PostgresSaver` checkpointer (`app/graph/checkpointer.py`, backed by app-db). `POST /runs` and `POST /runs/{id}/resume` (`app/api/run_routes.py`) are both synchronous — `graph.invoke()` blocks until the next interrupt or graph end and the response reflects that snapshot directly (SSE streaming was considered and deferred). `GET /runs/{id}` does not re-read the LangGraph checkpoint; it returns the last response cached by `app/runs/run_manager.py`, for reload/reconnect.

`GET /runs/{id}/trace` walks `graph.get_state_history()` (returned newest-first, re-sorted chronologically here) to expose per-step retry counts and the next node to run — useful for debugging why a run took the path it did.

### Backend module map (`server/app/`)

- `graph/nodes/` — one file per pipeline stage (`intent`, `schema_linking`, `schema_review`, `sql_generation`, `sql_review`, `validation`, `execution`)
- `sql/` — prompt building, few-shot retrieval, SQL validation (`sqlglot`-based), schema-citation/value-anchor checks that gate generated SQL before execution
- `knowledge/` — Qdrant collections for schema embeddings (`schema_<domain>`) and SQL few-shot examples (`sql_knowledge_<domain>`)
- `llm/` — LLM client abstraction; `azure_openai_client.py` actually talks to an Azure-OpenAI-compatible gateway (see `.env.example`), wrapped by `TokenCountingLLM` for cost tracking
- `db/` — `app_db.py` (fixed operational DB connection), `postgres_client.py` (target domain DB), `encryption.py` (Fernet for stored domain passwords)
- `observability/` — `run_logger` (per-run outcome logging used by both the API and CLI paths) and `cost_tracker`
- `runs/run_manager.py` — run registry + last-known-state cache in app-db, independent of the LangGraph checkpoint tables

### Frontend (`client/src/`)

Single-page React app, no router: `App.tsx` switches between views (`query`, `domain`) via local state, with a sidebar nav that also lists not-yet-built views (`soon: true`). `components/queryRun/` holds the multi-stage query UI (`StageRail`, `SchemaReviewCard`, `SqlReviewCard`, `ResultCard`, etc.) that mirrors the backend graph's stages and interrupt states one-to-one — when adding a new graph node or interrupt, the corresponding UI stage component and `stages.ts` likely need updating too.

### Relationship to `rag-practice`

This project is a from-scratch rebuild that reuses selected pieces from the sibling `rag-practice` project (see `docs/data-access-copilot-plan.md` section 2 for the exact reuse mapping, and the checkpointer module docstring for a concrete ported pattern). Don't assume feature parity — check the plan doc before assuming something from `rag-practice` also exists here.

## Documentation

- `docs/data-access-copilot-plan.md` — full build plan: scope tiers, reuse mapping from `rag-practice`, directory structure, the interrupt/resume design (section 5), and the vertical-slice implementation order (section 6: A. data layer → B. core pipeline → C. human-in-the-loop → D. cost/observability → E. multi-agent → F. MCP exposure → H. eval)
- `docs/agent-spec.md` — agent behavior spec
- `docs/kpi-schema-rag-mode-ablation.md` — KPI ablation results
- `docs/screen-spec.html` — UI design brief
