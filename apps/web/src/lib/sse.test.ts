import { parseSse } from "./sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("parseSse", () => {
  it("parses complete events", async () => {
    const stream = streamOf(
      'event: token\ndata: {"text":"hi"}\n\n',
      'event: done\ndata: {"conversation_id":"c1"}\n\n',
    );
    const events = [];
    for await (const e of parseSse(stream)) events.push(e);
    expect(events).toEqual([
      { event: "token", data: { text: "hi" } },
      { event: "done", data: { conversation_id: "c1" } },
    ]);
  });

  it("handles events split across chunks", async () => {
    const stream = streamOf("event: tok", 'en\ndata: {"text":"a', 'b"}\n\n');
    const events = [];
    for await (const e of parseSse(stream)) events.push(e);
    expect(events).toEqual([{ event: "token", data: { text: "ab" } }]);
  });

  it("handles multiple events in one chunk", async () => {
    const stream = streamOf(
      'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n',
    );
    const events = [];
    for await (const e of parseSse(stream)) events.push(e);
    expect(events.map((e) => e.data.text)).toEqual(["a", "b"]);
  });

  it("skips a corrupt frame instead of aborting the stream", async () => {
    const stream = streamOf(
      'event: token\ndata: {"text":"a"}\n\n',
      "event: token\ndata: {not json\n\n",
      'event: token\ndata: {"text":"b"}\n\n',
    );
    const events = [];
    for await (const e of parseSse(stream)) events.push(e);
    // The good frames on either side of the bad one still arrive.
    expect(events.map((e) => e.data.text)).toEqual(["a", "b"]);
  });

  it("joins multiple data lines with newlines before parsing", async () => {
    const stream = streamOf('event: token\ndata: {"text":\ndata: "ab"}\n\n');
    const events = [];
    for await (const e of parseSse(stream)) events.push(e);
    expect(events).toEqual([{ event: "token", data: { text: "ab" } }]);
  });
});
