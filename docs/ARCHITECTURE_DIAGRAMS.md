# Architecture Diagrams

Visual companion to [CODE_TOUR.md](CODE_TOUR.md) (where the code lives) and
[HOW_IT_WORKS.md](HOW_IT_WORKS.md) (what the product does). Every diagram here is
grounded in real files — the file names are clickable in your editor.

---

## 1. The whole system (containers)

Who talks to whom, and what each part is made of. The browser only ever talks
to the web app; the engine is never reachable directly.

```mermaid
flowchart TB
    subgraph Browser
        U["User's browser"]
    end

    subgraph web["apps/web · Next.js 15 (TypeScript)"]
        PAGES["Pages<br/>app/(workspace)/*"]
        BFF["BFF relay routes<br/>app/api/* → proxyToEngine()"]
        AUTH["better-auth<br/>(login, orgs)"]
    end

    subgraph engine["apps/engine · FastAPI (Python 3.12)"]
        API["HTTP routes /v1/*<br/>api/runs.py, chat.py, …"]
        AGENTS["Agent runtime<br/>agents/*"]
        INDEX["Indexing + retrieval<br/>indexing/*"]
        ROUTER["ModelRouter<br/>llm/router.py"]
        WORKER["arq background worker<br/>worker.py"]
    end

    subgraph infra["Backing services (docker-compose.dev.yml)"]
        PG[("Postgres 16<br/>+ pgvector")]
        REDIS[("Redis 7<br/>queue + wake-ups")]
        MINIO[("MinIO<br/>S3 backups")]
    end

    subgraph external["Outside world"]
        LLM["LLM providers<br/>(via LiteLLM)"]
        GH["GitHub / GitLab / Bitbucket"]
        SANDBOX["Docker sandbox<br/>(--network none)"]
    end

    U -->|HTTPS| PAGES
    U -->|HTTPS| BFF
    PAGES --> AUTH
    BFF -->|"signed service JWT (HS256)"| API
    API --> AGENTS
    API --> INDEX
    AGENTS --> ROUTER
    INDEX --> ROUTER
    ROUTER -->|"only exit for model calls"| LLM
    AGENTS --> WORKER
    WORKER --> SANDBOX
    AGENTS --> GH
    API --> PG
    WORKER --> PG
    AGENTS -->|"ping: new events"| REDIS
    WORKER --> MINIO
```

**The one rule to remember:** the browser → web app → (signed JWT) → engine.
The engine trusts a request only if it carries a JWT signed with
`ENGINE_SERVICE_SECRET` (checked in `engine/auth.py`). `/healthz` is the only
public route.

---

## 2. Request flow — a plain chat message

The simplest end-to-end path. Good to trace first because it touches every
layer once.

```mermaid
sequenceDiagram
    participant B as Browser
    participant W as Web BFF<br/>(app/api/chat)
    participant A as better-auth
    participant E as Engine<br/>(api/chat.py)
    participant R as ModelRouter
    participant DB as Postgres

    B->>W: POST /api/chat {message}
    W->>A: is there a valid session?
    A-->>W: yes → user id
    W->>W: sign service JWT (sub = user id)
    W->>E: POST /v1/chat  (Authorization: Bearer JWT)
    E->>E: verify JWT (engine/auth.py)
    E->>DB: pin session to user (row-level security)
    E->>R: complete(tier="cheap", messages)
    R-->>E: streamed tokens
    E-->>W: Server-Sent Events (token stream)
    W-->>B: relayed SSE stream
    E->>DB: save the finished message
```

Key idea: the web app never holds a model key or talks to a provider. It only
proves *who you are* and forwards. All intelligence lives behind the JWT.

---

## 3. The agent run — state machine

A run is a state machine stored in the `agent_runs.status` column. Every arrow
is a transition written to the `agent_events` table, which *is* the timeline you
see on the run page.

```mermaid
stateDiagram-v2
    [*] --> QUEUED: POST /v1/runs
    QUEUED --> PLANNING: worker picks it up
    PLANNING --> AWAITING_APPROVAL: plan + task board saved
    AWAITING_APPROVAL --> EXECUTING: human approves (api/runs.py)
    AWAITING_APPROVAL --> FAILED: human rejects
    EXECUTING --> REVIEWING: all tasks done
    EXECUTING --> FAILED: a task fails 3×, or budget exhausted
    REVIEWING --> EXECUTING: reviewer requests changes (1 revision)
    REVIEWING --> FAILED: still not approved after 1 revision
    REVIEWING --> COMPLETED: approved → gates pass → PR opened
    REVIEWING --> FAILED: a gate blocks (tests / secrets / deps)
    COMPLETED --> [*]
    FAILED --> [*]
```

The human approval gate between `AWAITING_APPROVAL` and `EXECUTING` is the
safety line: no code is written until you approve the plan. Everything failure
flows through one function (`_fail_run` in `agents/runner.py`) so a run can never
end in a half-state.

---

## 4. The run pipeline — which file owns each step

This is the same order `agents/runner.py::_execute_tasks` calls things. Steps
5–7 are **gates**: any one of them failing fails the run and *no pull request
opens*.

```mermaid
flowchart TD
    A["1 · Plan<br/>product_manager.py → create_plan()"] --> B{"2 · Human approves?<br/>api/runs.py"}
    B -->|reject| X["FAILED<br/>(records a 'preference' memory)"]
    B -->|approve| C["3 · Execute tasks<br/>supervisor.py routes → engineer.py does"]
    C --> D["4 · Review<br/>reviewer.py (approve / request changes)"]
    D -->|request changes| C2["one revision round<br/>execute_revision()"]
    C2 --> D2["re-review (final)"]
    D --> E
    D2 --> E["5 · GATE: tests in Docker<br/>sandbox/runner.py + qa.py self-fix loop"]
    E -->|fail after QA retries| X
    E --> F["6 · GATE: secrets scan<br/>security/secrets_scanner.py"]
    F -->|leak found| X
    F --> G["7 · GATE: dependency scan<br/>security/dependency_scanner.py"]
    G -->|vulnerable dep| X
    G --> H["8 · Publish<br/>push branch + open PR/MR<br/>github.py / integrations/*"]
    H --> Z["COMPLETED<br/>(records plan + outcome as memory)"]
```

---

## 5. Inside one task — the shared agent loop

Every engineer role (Backend, Frontend, DevOps, QA, Reviewer) uses the *same*
loop in `agents/loop.py::run_tool_loop`. Only three things differ per role, all
from `agents/registry.py`: the **system prompt**, the **model tier**, and the
**allowed tools** (deny-by-default).

```mermaid
flowchart TD
    START["execute_task()<br/>engineer.py"] --> ASK["ask the model<br/>ModelRouter.complete_with_tools()"]
    ASK --> Q{"did the model<br/>ask for a tool?"}
    Q -->|"no (just text)"| DONE["that text is the<br/>task summary → return"]
    Q -->|yes| REASON["record reasoning<br/>(agent.reasoning event)"]
    REASON --> TOOL["run the tool<br/>tools.py::call_tool — jailed"]
    TOOL --> AUDIT["record tool.called event<br/>+ audit_logs row"]
    AUDIT --> FEED["feed result back to the model"]
    FEED --> ASK
    Q -->|"24 turns reached"| FAIL["AgentLoopError → attempt fails"]
```

Two safety limits live here: **MAX_TURNS = 24** (a task can't loop forever) and
every file path passes through the **jail** (`workspace/jail.py`) before any read
or write. `LLM_FAKE=1` swaps the model for deterministic canned steps, so this
whole loop is testable offline.

---

## 6. Live timeline — how the UI updates without polling hard

The clever bit (`events/bus.py`): **Postgres holds the events, Redis only says
"go look".** A Redis ping carries no data. If Redis is down, a 2-second
heartbeat re-reads Postgres anyway — so you lose a little latency, never an
event.

```mermaid
sequenceDiagram
    participant RUN as Run worker<br/>(runner.py)
    participant DB as Postgres<br/>agent_events
    participant RD as Redis
    participant STR as Stream route<br/>/v1/runs/{id}/events/stream
    participant UI as Run page (SSE)

    RUN->>DB: INSERT event + commit
    RUN->>RD: publish ping "new rows"
    RD-->>STR: ping (or 2s heartbeat if silent)
    STR->>DB: read events since last id
    STR-->>UI: Server-Sent Event(s)
    Note over STR,UI: Redis down? heartbeat still<br/>re-reads Postgres every 2s
```

---

## 7. The data model (the tables that matter)

```mermaid
erDiagram
    agent_runs ||--o{ agent_tasks : "has"
    agent_runs ||--o{ agent_events : "has (the timeline)"
    agent_runs ||--o{ artifacts : "produces"
    repositories ||--o{ agent_runs : "target of"
    repositories ||--o{ code_chunks : "indexed into"
    repositories ||--o{ work_items : "planned backlog"
    repositories ||--o{ knowledge_items : "memory"
    repositories ||--o{ generated_documents : "docs"
    conversations ||--o{ messages : "chat"

    agent_runs {
        uuid id
        text user_id "better-auth id, no FK"
        text org_id
        string status
        numeric total_cost_usd
        string branch_name
        string pr_url
    }
```

Notes that explain the shape:
- **`user_id` / `org_id` are plain text, not foreign keys.** Identity lives in
  better-auth's own tables (created by a separate migration), and the engine
  only references the ids — see the CLAUDE.md conventions.
- **Row-level security** is enforced *inside Postgres* on the ownership-carrying
  tables, so even raw SQL on an API session can't read another user's rows
  (`db/rls.py`, `db/visibility.py`).
- **`code_chunks`** holds `vector(768)` embeddings via pgvector — data and
  vectors in one store (ADR-0003), no separate vector database.

---

## How to use these diagrams

Pair each with the code:

| Diagram | Read alongside |
|---|---|
| 1 · Containers | `CLAUDE.md`, the ADRs in `docs/architecture/adr/` |
| 2 · Chat flow | `apps/web/src/app/api/chat/route.ts`, `engine/api/chat.py` |
| 3 · Run states | `engine/db/enums.py` (`RunStatus`), `engine/agents/runner.py` |
| 4 · Run pipeline | `engine/agents/runner.py::_execute_tasks` (top to bottom) |
| 5 · Agent loop | `engine/agents/loop.py`, `engine/agents/registry.py` |
| 6 · Timeline | `engine/events/bus.py`, `engine/api/runs.py` (stream route) |
| 7 · Data model | `engine/db/models.py` |
