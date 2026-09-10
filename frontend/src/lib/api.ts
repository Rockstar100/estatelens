import type {
  ChatMessage,
  Property,
  PropertyListResponse,
  SourcesResponse,
  StreamEvent,
} from "@/types";

const BASE = "/api";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface PropertyQuery {
  text?: string;
  source?: string;
  record_type?: string;
  city?: string;
  transaction_type?: string;
  property_type?: string;
  bedrooms?: number;
  bedrooms_min?: number;
  budget_min?: number;
  budget_max?: number;
  currency?: string;
  price_basis?: string;
  sort?: string;
  page?: number;
  page_size?: number;
}

export function listProperties(q: PropertyQuery): Promise<PropertyListResponse> {
  const params = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  return json<PropertyListResponse>(`/properties?${params.toString()}`);
}

export function getProperty(id: string): Promise<Property> {
  return json<Property>(`/properties/${encodeURIComponent(id)}`);
}

export function getSources(): Promise<SourcesResponse> {
  return json<SourcesResponse>("/sources");
}

export interface ChatContext {
  selected_property_ids: string[];
  last_result_ids: string[];
  filters: Record<string, unknown>;
}

/**
 * Streams a chat answer. Parses our SSE contract (event: <type> / data: <json>)
 * and calls `onEvent` for each. Returns an abort function.
 */
export function streamChat(
  messages: { role: "user" | "assistant"; content: string }[],
  context: ChatContext,
  onEvent: (e: StreamEvent) => void,
  onDone: () => void,
): () => void {
  const controller = new AbortController();
  let timedOut = false;
  // Hard ceiling so a provider backoff loop cannot leave "Searching…" forever.
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 75_000);

  (async () => {
    try {
      const res = await fetch(BASE + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages, context }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        let detail = "";
        try {
          const raw = await res.text();
          try {
            detail = JSON.parse(raw).detail ?? "";
          } catch {
            detail = raw;
          }
        } catch {
          detail = res.statusText;
        }
        if (typeof detail !== "string") detail = JSON.stringify(detail);
        detail = detail.replace(/<[^>]*>/g, "").trim().slice(0, 200);
        onEvent({
          type: "error",
          category: res.status === 429 ? "rate_limited" : "internal",
          message: detail || `Request failed (${res.status})`,
          request_id: null,
        });
        onDone();
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const dataLine = block
            .split("\n")
            .find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          try {
            onEvent(JSON.parse(dataLine.slice(5).trim()) as StreamEvent);
          } catch {
            /* skip malformed frame */
          }
        }
      }
      onDone();
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        if (timedOut) {
          onEvent({
            type: "error",
            category: "timeout",
            message: "The model took too long to respond. Please try again.",
            request_id: null,
          });
        }
        // User Stop: ChatPage clears pending; no error toast.
      } else {
        onEvent({
          type: "error",
          category: "internal",
          message: (err as Error).message || "Network error",
          request_id: null,
        });
      }
      onDone();
    } finally {
      window.clearTimeout(timeoutId);
    }
  })();

  return () => {
    window.clearTimeout(timeoutId);
    controller.abort();
  };
}

export function toWireMessages(
  msgs: ChatMessage[],
): { role: "user" | "assistant"; content: string }[] {
  return msgs
    .filter((m) => m.content.trim().length > 0 && !m.error && !m.stopped)
    .map((m) => ({ role: m.role, content: m.content }));
}
