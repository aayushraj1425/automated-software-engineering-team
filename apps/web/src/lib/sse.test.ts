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
});
