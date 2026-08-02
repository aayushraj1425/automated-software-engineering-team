# Rendering chat replies

**Status:** shipped · **Design note**

A chat reply was rendered as plain text in a single `whitespace-pre-wrap`
paragraph. Any code in the answer sat in the same blob as the prose — no
formatting, no highlighting, and nothing to copy without selecting by hand. For a
tool whose answers are often code, that is the wrong default.

## What changed

Assistant replies now render as Markdown. `markdown-message.tsx` uses
`react-markdown` with `remark-gfm` (tables, lists, links) and custom renderers for
the dark theme; a fenced code block becomes a `code-block.tsx`:

- a header with the **language label** and a one-click **copy** button,
- syntax highlighting (Prism, dark theme),
- and a **collapse** for long blocks, so a long snippet doesn't bury the prose.

User messages stay plain text, and the existing **Sources** and **Remembered**
sections under an answer are untouched.

## Why these choices

- **Prism highlighting is synchronous**, so it re-highlights cleanly as tokens
  stream in — no async flash. (A very long streamed reply can memoize the parse if
  it ever feels janky; typical replies don't need it.)
- The **copy button and language label live in one `CodeBlock`** shared with the
  run diff viewer through a common `CopyButton` primitive
  ([AGENT_TIMELINE_LEGIBILITY.md](../runs-ui/AGENT_TIMELINE_LEGIBILITY.md)), so
  "code you can copy, not paste-wrestle" is consistent everywhere code appears.
- Streaming is unchanged: tokens still append to the message's `content`, and the
  Markdown renderer simply renders the growing string. The blinking cursor stays.

## Deliberate scope

Presentation only — no change to the chat API, the SSE token contract, or how
messages persist. The `/chat` page remains a single grounded assistant; the
multi-agent view is a Runs concept.
