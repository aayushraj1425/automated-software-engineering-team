export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

/** Parse a text/event-stream body into typed events (browser fetch streams). */
export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let event = "message";
        const dataLines: string[] = [];
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          // Per the SSE spec a frame may carry several data: lines that join
          // with newlines; concatenating them directly would corrupt the JSON.
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (dataLines.length === 0) continue;
        const parsed = tryParse(dataLines.join("\n"));
        // A single corrupt frame must not abort a whole live run: skip it and
        // keep reading rather than rejecting the generator mid-stream.
        if (parsed !== undefined) yield { event, data: parsed };
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** Parse one frame's JSON payload, returning undefined (not throwing) on a
 * malformed frame so the caller can skip it and keep the stream alive. */
function tryParse(data: string): Record<string, unknown> | undefined {
  try {
    return JSON.parse(data);
  } catch {
    return undefined;
  }
}
