import type {
  Dashboard, ImpactReport, ObjectSummary, ReviewPayload, WhereUsed, WorkspaceInfo,
} from "./types";

/**
 * The API lives at the origin root while the app is served under /app/, so every
 * call is absolute. In dev, Vite proxies the same paths to a local service.
 */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `요청 실패 (${res.status})`);
  }
  return (await res.json()) as T;
}

const post = <T,>(path: string, body: unknown) =>
  call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  workspaces: () => call<WorkspaceInfo[]>("/workspaces"),
  dashboard: (workspace?: string | null) =>
    call<Dashboard>(`/dashboard${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ""}`),
  reindex: (workspace: string) =>
    post<{ status: string }>(`/workspaces/${encodeURIComponent(workspace)}/reindex`, {}),

  impact: (objects: string[], hops: number, workspace?: string | null) =>
    post<ImpactReport>("/impact", { objects, hops, workspace }),
  ask: (prompt: string, hops: number, workspace?: string | null, select = 2) =>
    post<ImpactReport>("/ask", { prompt, hops, workspace, select }),
  changes: (revision_range: string | null, hops: number, workspace?: string | null) =>
    post<ImpactReport>("/changes", { revision_range, hops, workspace }),

  review: (revision_range: string | null, hops: number, workspace?: string | null) =>
    post<ReviewPayload>("/review", { revision_range, hops, workspace }),

  search: (q: string, workspace?: string | null, limit = 12) =>
    call<ObjectSummary[]>(
      `/objects?q=${encodeURIComponent(q)}&limit=${limit}` +
        (workspace ? `&workspace=${encodeURIComponent(workspace)}` : ""),
    ),
  whereUsed: (object: string, workspace?: string | null) =>
    call<WhereUsed>(
      `/where-used?object=${encodeURIComponent(object)}` +
        (workspace ? `&workspace=${encodeURIComponent(workspace)}` : ""),
    ),

  agentStatus: () => call<{ configured: boolean; agent_name: string }>("/agent/status"),
};

export interface AgentEvent {
  type: "conversation" | "delta" | "tool" | "done" | "error";
  data: Record<string, string>;
}

/**
 * Server-sent events from the Foundry agent. Parsed by hand rather than with
 * EventSource because the request is a POST carrying the screen context.
 */
export async function streamAgent(
  body: { message: string; conversation_id?: string | null; context?: unknown },
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/agent/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    onEvent({ type: "error", data: { message: `에이전트 응답 실패 (${res.status})` } });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const typeLine = chunk.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!typeLine || !dataLine) continue;
      onEvent({
        type: typeLine.slice(7).trim() as AgentEvent["type"],
        data: JSON.parse(dataLine.slice(6)),
      });
    }
  }
}
