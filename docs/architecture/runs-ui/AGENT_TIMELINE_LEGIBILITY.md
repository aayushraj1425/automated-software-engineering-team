# Making the run timeline legible

**Status:** shipped · **Design note**

The run timeline is a live stream of everything the agent team does. It was
readable but flat: every agent's lines looked the same, a tool call was a single
sentence with its detail hidden, and the diff of all the changes was one long
unified-diff blob you had to select and copy by hand. This change makes it easy to
see *which agent thought what*, and to review the changes without copy-paste.

## What changed

- **Each agent has a colour.** `agent-style.ts` maps every role to a distinct
  accent (Product Manager violet, Backend sky, Frontend fuchsia, DevOps orange,
  Reviewer amber, QA emerald, System zinc), mirroring the `status-chip.tsx`
  colour-map pattern. A coloured dot sits before each event's agent name, and the
  per-agent filter chips carry the same colour — so the chips read as a legend and
  clicking one isolates that agent's thread. The filter itself is unchanged
  ([TIMELINE_AGENT_FILTER.md](TIMELINE_AGENT_FILTER.md)).
- **Reasoning reads as a thinking card.** An `agent.reasoning` event renders with
  the agent's colour as a left border and an "is thinking" label, keeping the
  existing preview-and-expand behaviour ([AGENT_REASONING_TIMELINE.md](../agents/AGENT_REASONING_TIMELINE.md)).
- **Actions expand on demand.** A `tool.called` event is a one-line summary that
  expands to show the tool, its argument summary, and the result preview already
  in the payload — so "what each agent actually did" is one click away, not hidden.
- **The diff is per-file.** `DiffView` splits the unified diff (`parse-diff.ts`)
  into one collapsible section per file, each with a `+`/`−` count, the existing
  line colouring, and a **copy** button; a **Download .diff** button saves the
  whole patch. The pull-request link already covers "apply".

## Deliberate scope

- Presentation only — no engine or SSE-contract change. The events and their
  payloads are exactly as before; this is a nicer view over the same data.
- The event → text mapping stays in `event-text.ts` (`describeEvent`,
  `reasoningOf`, `timelineAgents`, `agentName`); the components consume it rather
  than re-deriving text, so the two can't drift.
- Diff line colouring moved out of `run-detail-panel.tsx` into `DiffView` unchanged
  — grouped by file, not rewritten.
