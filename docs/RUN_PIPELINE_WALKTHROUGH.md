# Run Pipeline Walkthrough

A line-by-line-ish trace of what happens from "user submits a feature request"
to "a pull request is open". Where [CODE_TOUR.md](CODE_TOUR.md) is the *map*,
this is the *guided walk* of the single most important path in the codebase.

Everything below lives in `apps/engine/src/engine/`. Open
`agents/runner.py` next to this document — it is the spine, and every step is a
small named function inside it.

---

## The two entry points

A run is split into two background phases, because a human approves in between.

1. `plan_run(run_id)` — after `POST /v1/runs`. Plans, then stops.
2. `execute_tasks(run_id)` — after the human approves. Does the work.

Both are wrapped the same way:

```python
async def plan_run(run_id):
    with _tracer.start_as_current_span("run.plan", ...):
        await _guarded(_plan_run, run_id)   # <- the real work
    await capture_run_memory(run_id)         # remember what happened
    await notify_run_outcome(run_id)         # Slack, if connected
```

`_guarded` (runner.py:197) is the safety net: **whatever throws inside a run
becomes a FAILED run, never a crashed worker.** This is why you never see a run
stuck in `PLANNING` forever — an exception funnels to `_fail_run`.

---

## Phase 1 — Planning (`_plan_run`, runner.py:218)

Step by step:

1. **Load and guard.** Fetch the run; bail unless it is still `QUEUED` (so a
   double-dispatch can't run twice). Assert the repository still exists — a
   repo can't be disconnected while a run is active, so this is safe.

2. **Set the run's context.** Two `ContextVar`s are set here and they matter a
   lot:
   - `provider_keys_var` — the owner's decrypted BYO model keys ride the async
     context all the way down to `ModelRouter`. No keys → the `.env` keys apply.
   - `audit_user_var` — the owner's id rides down to the tool-call audit trail,
     so an `audit_logs` row stays attributable even after the run is deleted.

3. **Move to `PLANNING`**, emit `run.started`, commit, ping the timeline.

4. **Recall memory** (`_recall_for_planning`, runner.py:280). Hybrid search over
   past `knowledge_items` for this repo, formatted into the planner's prompt.
   Wrapped in try/except — *recall failing must never fail the run.* If it finds
   anything it emits a `memory.recalled` event so you can see it worked.

5. **Open the workspace** (`_open_workspace`). Clones the repo into a jailed
   per-run folder. Offline trick: under `LLM_FAKE=1` with a non-local URL it
   creates an empty scratch git repo instead of touching the network.

6. **Call the Product Manager** (`product_manager.py::create_plan`). Returns a
   structured plan: a summary + a list of tasks, each with a role, a title, a
   description, and `depends_on` indices.

7. **Save the task board.** Each plan task becomes an `AgentTask` row. Note the
   dependency remap (runner.py:270): the PM emits dependencies as *positions*
   (task 3 depends on task 1); the code converts those to the real DB uuids
   after flushing the rows.

8. **Stop at `AWAITING_APPROVAL`.** Nothing else runs. Commit, ping. The run now
   waits for a human on the run page.

> If planning itself throws, `_guarded` fails the run, and `capture_run_memory`
> still records what it can. A run waiting for approval is *not* terminal, so
> capture does nothing yet.

---

## The human gate

`POST /v1/runs/{id}/decision` (in `api/runs.py`) flips the run to `EXECUTING`
and dispatches `execute_tasks`, **or** rejects it. A rejection is interesting:
it records a `preference` memory ("the team planned X, the human said no"), so a
future run's planner recalls it. Approval can also edit the plan in place first
(retitle/drop tasks) — dangling dependencies get cleaned up.

---

## Phase 2 — Execution (`_execute_tasks`, runner.py:308)

This is the heart. Read it in five beats.

### Beat 1 — Rebuild the board in memory
Load the run (must be `EXECUTING`), reload the owner's keys and audit id (a
fresh worker process may be running this phase), read all `AgentTask` rows
ordered by sequence, and convert them to lightweight `TaskState` dicts.

### Beat 2 — Run the supervisor graph
```python
graph = build_supervisor_graph(_make_task_executor(run_id, request, ws, known_ids))
final = await graph.ainvoke({"tasks": board, ...}, {"recursion_limit": 100})
```

Two pieces to understand:

**The supervisor** (`supervisor.py`) is a **LangGraph state machine with zero
LLM calls** — pure deterministic scheduling. Its loop is `schedule → execute →
schedule → …`:
- *Eligible* = pending AND every dependency is done. Among eligible, lowest
  sequence runs first.
- A thrown execution returns the task to `pending`; after `MAX_RETRIES = 2`
  (three attempts total) the task is `FAILED` and the whole run fails with a
  readable reason.
- No eligible tasks but some still pending = **dependency deadlock**, surfaced
  as a failure (it can't silently hang).
- On finalize, any still-pending tasks are marked `skipped`.

**The task executor** (`_make_task_executor`, runner.py:685) is the bridge
between the pure graph and the messy real world. For each task it:
1. Checks the budget (`_check_budget`) — over the cost cap → `BudgetExceeded`,
   the run fails before spending more.
2. Flips the row to `IN_PROGRESS`, emits an event.
3. Calls `engineer.py::execute_task` (the actual agent).
4. On success, marks `DONE`, records token/cost usage, and — importantly —
   reports back any **board changes the agent made mid-task**: new tasks it
   discovered (`add_task` tool) and tasks it skipped (`update_task_status`).
   The supervisor merges those and schedules them like anything else.

### Beat 3 — One task, inside the agent loop
`engineer.py::execute_task` → `loop.py::run_tool_loop`. This is the same loop
for every role; see diagram 5 in [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md).
The essentials:
- The role name picks the **prompt + model tier + allowed tools** from
  `registry.py` (deny-by-default: a Frontend agent literally cannot call a tool
  it wasn't granted).
- Loop: ask the model → if it returns tool calls, run them through the jailed
  `tools.py::call_tool` and feed results back → repeat. When the model replies
  with plain text and no tool call, that text is the task summary and the loop
  ends.
- `MAX_TURNS = 24` caps it. The text on a tool-calling turn is the agent's
  *reasoning* (surfaced as `agent.reasoning`); every tool call is audited.
- **Offline mode** (`_execute_offline`) runs a fixed script (write a file, git
  commit) through the *same* tools, so the whole pipeline is provable without a
  model.

### Beat 4 — Sync the board, decide the branch
After the graph returns, sync the in-memory task statuses back to Postgres. If
`final["failure"]` is set, `_fail_run` and stop. Otherwise move to `REVIEWING`.

### Beat 5 — Review, then the gates
```python
verdict = await _review(...)
if verdict == REQUEST_CHANGES:
    # group findings by role, each role fixes its own, then re-review ONCE
    ...
if verdict != APPROVE:
    _fail_run("the reviewer did not approve ... after one revision")
    return
```

The Reviewer (`reviewer.py`) reads the full diff and returns approve or
role-tagged findings. Exactly **one** revision round: each implicated role runs
`execute_revision` on its own findings, then a final re-review. Second verdict
is final.

Then the four sequential gates — **any one fails the run and no PR opens**:

| Order | Function | What blocks it |
|---|---|---|
| 5 | `_sandbox_gate` (runner.py:512) | tests fail in the Docker sandbox — but first the **QA agent** gets `QA_MAX_ATTEMPTS` tries to fix them (read failure → edit → re-run) |
| 6 | `_security_gate` (runner.py:597) | a leaked secret in the diff (`secrets_scanner.py`) |
| 7 | `_dependency_gate` (runner.py:631) | a known-vulnerable dependency added to a manifest |
| 8 | `_publish` (runner.py:462) | (not a gate) push branch, open PR/MR/PR on GitHub/GitLab/Bitbucket |

The sandbox gate is the most sophisticated: a failure doesn't immediately fail
the run — it loops the QA agent up to `QA_MAX_ATTEMPTS`, re-running the sandbox
after each fix, and only fails if tests still fail at the end. Every attempt is
a `sandbox.run` + `qa.attempt` event on the timeline.

### Publish
`_publish` is host-aware. It looks up the owner's encrypted host connection: a
GitLab repo opens a **merge request** with the GitLab token, Bitbucket opens a
Bitbucket PR, a GitHub repo opens a PR with the env `GITHUB_TOKEN`. A repo on
none of them (or an offline scratch repo) just pushes. The PR body is built by
`build_pull_request_body` and carries the full Definition-of-Done checklist,
unchecked, identical across all three hosts.

Finally: set `COMPLETED`, stamp `finished_at`, emit `run.finished`. Back up in
the entry point, `capture_run_memory` now records the approved plan as a
`decision` and the outcome (PR url or failure) as an `outcome`, so the next run
can recall them.

---

## The three cross-cutting patterns worth internalizing

1. **Every DB write is its own `async with session_scope()` block, then
   `_commit_and_ping`.** Commit to Postgres (the record), then ping Redis (the
   wake-up). The run never holds one long transaction across model calls, which
   can take minutes.

2. **One failure funnel.** `_fail_run` is the *only* way a run ends in failure —
   a crash, a task giving up, the reviewer refusing, any gate blocking. They
   physically cannot drift apart because they all call the same four lines.

3. **Events are the source of truth for the UI.** The code never "tells the
   frontend" anything directly. It writes rows to `agent_events`; the timeline,
   the task board, the cost widget, and the diff viewer are all just views over
   that table (plus the workspace). This is why the whole thing is auditable and
   resumable.

---

## Where to poke to learn fastest

- Set a breakpoint (or add a `log.info`) in `_make_task_executor._execute` and
  run one offline task — watch the board mutate.
- Read `registry.py` once fully: it is the single source for *who can do what*.
- Compare `_sandbox_gate` to `_security_gate` — same shape, and it teaches you
  the gate pattern in two reads.
- Then read `supervisor.py` end to end (153 lines) — it is the cleanest file in
  the project and the whole scheduling model fits in your head.
