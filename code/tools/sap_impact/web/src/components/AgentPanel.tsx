import { useEffect, useRef, useState } from "react";
import { api, streamAgent } from "../api";

interface Message {
  role: "user" | "assistant";
  text: string;
  tools?: string[];
}

const STARTERS = [
  "이번 전송분에서 가장 위험한 변경은 뭐야?",
  "ZORDER_HDR 고치면 어디까지 영향 가?",
  "구매요청 승인 로직 바꾸면 뭘 테스트해야 해?",
];

/**
 * The chat panel talks to the Foundry agent through the service, and the agent
 * answers only from the impact API. It is a second way into the same facts the
 * screens show, not a separate source of truth -- which is why the panel prints
 * the tool the agent called.
 */
export function AgentPanel({ context, seed, onClose }: {
  context: Record<string, unknown>; seed?: string | null; onClose: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [available, setAvailable] = useState<boolean | null>(null);
  const conversation = useRef<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.agentStatus()
      .then((s) => setAvailable(s.configured))
      .catch(() => setAvailable(false));
  }, []);

  useEffect(() => {
    if (seed) void send(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [messages]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: question },
                        { role: "assistant", text: "", tools: [] }]);
    setBusy(true);
    await streamAgent(
      { message: question, conversation_id: conversation.current, context },
      (event) => {
        setMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (event.type === "conversation") conversation.current = event.data.id;
          if (event.type === "delta") last.text += event.data.text ?? "";
          if (event.type === "tool") last.tools = [...(last.tools ?? []), event.data.name];
          if (event.type === "error") last.text = event.data.message ?? "오류";
          return next;
        });
      },
    ).catch((err: Error) => {
      setMessages((current) => {
        const next = [...current];
        next[next.length - 1].text = err.message;
        return next;
      });
    });
    setBusy(false);
  }

  return (
    <aside className="agent" aria-label="분석 에이전트">
      <header className="agent-head">
        <span className="pill accent">에이전트</span>
        <span className="small muted grow truncate">
          {available === false ? "미설정" : "Foundry · 영향 분석 도구 연결됨"}
        </span>
        <button className="btn ghost sm" onClick={onClose} aria-label="닫기">✕</button>
      </header>

      <div className="agent-body" ref={bodyRef}>
        {available === false && (
          <div className="notice">
            <div className="notice-title">에이전트가 아직 연결되지 않았습니다</div>
            <div className="small">
              FOUNDRY_PROJECT_ENDPOINT 환경변수와 관리 ID 권한을 설정하면 이 패널에서 대화할 수
              있습니다. 화면의 분석 기능은 에이전트 없이도 동작합니다.
            </div>
          </div>
        )}

        {messages.length === 0 && available !== false && (
          <div className="col">
            <span className="small muted">
              지금 보고 있는 화면 정보를 함께 전달합니다. 답변의 근거는 화면과 동일한 참조 그래프입니다.
            </span>
            <div className="suggestions">
              {STARTERS.map((s) => (
                <button key={s} className="suggestion" onClick={() => void send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, i) => (
          <div key={i} className={`msg ${message.role}`}>
            <span className="msg-role">{message.role === "user" ? "나" : "에이전트"}</span>
            {message.tools && message.tools.length > 0 && (
              <span className="tool-trace">↳ 도구 호출: {message.tools.join(", ")}</span>
            )}
            <div className="msg-body">
              {message.text || (busy && i === messages.length - 1 ? "분석 중…" : "")}
            </div>
          </div>
        ))}
      </div>

      <div className="agent-foot">
        <textarea
          id="agent-input"
          value={input}
          placeholder="예: 이번 변경에서 QA가 꼭 봐야 할 게 뭐야?"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(input);
            }
          }}
        />
        <button className="btn primary" disabled={busy || !input.trim()}
                onClick={() => void send(input)}>보내기</button>
      </div>
    </aside>
  );
}
