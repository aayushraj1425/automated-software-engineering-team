# How ASEP Works

Read this first. Plain language, real file names, no jargon.

## What the app does today

You sign in and can do two things: **chat** with an AI that answers with
citations into your connected repository, and **start a run** — describe a
feature and an AI agent team plans it, writes the code, reviews it, tests it
in a sandbox, scans it for leaked secrets, and opens a pull request.

## The three processes

```mermaid
flowchart LR
    B[Your browser] -->|1. sends your message| W["Web app<br/>Next.js on :3000"]
    W -->|2. checks you are signed in,<br/>forwards the message| E["Engine<br/>FastAPI on :8000"]
    E -->|3. asks the AI model| L["Gemini API"]
    L -->|4. words stream back| E
    E -->|5. words stream back| W
    W -->|6. words appear live| B
    E -->|7. saves the conversation| P[("Postgres<br/>:5433")]
```

- **Web app** (`apps/web`) — the pages you see, sign-in, and a thin relay to the engine.
- **Engine** (`apps/engine`) — Python service that talks to the AI models and the database.
- **Postgres** — stores users, conversations, messages, and agent runs.

## One chat message, step by step

1. You press Enter. `apps/web/src/components/chat/chat-panel.tsx` sends your
   text to `/api/chat`.
2. `apps/web/src/app/api/chat/route.ts` checks your login session, then
   forwards the request to the engine with a signed pass
   (a short-lived token proving "the web app sent this").
3. The engine (`apps/engine/src/engine/api/chat.py`) loads your conversation
   history from Postgres.
4. `engine/llm/router.py` picks the model (set by the `MODEL_*` variables in
   `.env`) and calls it.
5. Each word streams back through the same path and appears on your screen.
6. When the reply finishes, the engine saves both messages to Postgres.

Set `LLM_FAKE=1` in `.env` and the engine skips step 4 and returns a canned
reply — that's how tests run without an API key.

## The agent team (Phases 1–3)

A team of AI agents that ships a feature for you:

```mermaid
flowchart TD
    A[You describe a feature] --> B[Product Manager agent<br/>writes a plan: spec + task list]
    B --> C{You approve the plan?}
    C -->|no| X[Run ends]
    C -->|yes| D[Supervisor hands each task to<br/>Backend / Frontend / DevOps agents]
    D --> E[Agents edit code in an isolated<br/>copy of your repository]
    E --> F[Reviewer agent checks the changes]
    F -->|problems found| D
    F -->|approved| S[Tests run in a Docker sandbox<br/>network unplugged]
    S -->|tests fail| X2[Run fails — no pull request]
    S -->|tests pass| SEC[Secrets scan of the diff]
    SEC -->|leak found| X2
    SEC -->|clean| G[Pull request opened on GitHub]
```

The whole flow above exists now. Open `/runs`, describe a feature, and the
Product Manager reads a clone of your repository and writes a plan; after you
press Approve, the engineer agents edit files and make git commits inside
that clone — never in your real repository. The Reviewer then checks the full
diff: it can send findings back to the engineers once, and its second verdict
is final. After approval two gates run: the run's tests execute in a
disposable Docker container with the network unplugged, and the diff is
scanned for leaked keys — failing either one fails the run and no pull
request opens. On a clean pass the branch is pushed and — when the repository
is on GitHub and `GITHUB_TOKEN` is set in `.env` — a pull request opens,
linked from the run page. Every step lands in the timeline. With `LLM_FAKE=1`
the same pipeline runs without an AI model (a fixed plan, real files, real
commits) — that's how the tests work. Progress lives in
[BACKLOG.md](BACKLOG.md).

The agents can also *understand* a connected repository (Phase 2): it is
indexed into searchable chunks, chat answers cite real files and lines, and
the agents use the same search as a tool while they work.

The team can also *plan* and *remember* (Phases 4–5). On `/planning`, a
Scrum Master agent turns a one-line goal into an estimated, dependency-aware
backlog and flags what is blocked. On `/knowledge`, you can browse the
platform's long-term memory: every finished run saves its approved plan and
its outcome, a rejected plan is saved as a team preference, and the next
time a run is planned the most relevant memories are recalled into the
planner's context automatically.

## Run it

```sh
pnpm db:up        # start Postgres, Redis, MinIO in Docker
pnpm db:migrate   # create/update database tables
pnpm dev          # web on http://localhost:3000, engine on :8000
```

Sign up at `http://localhost:3000`, open the chat, send a message.
