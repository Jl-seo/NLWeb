import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ImpactResult } from "../components/ImpactResult";
import { Empty, ErrorBox, Panel } from "../components/ui";
import type { ImpactReport } from "../types";

type Mode = "objects" | "ask" | "changes";

const PLACEHOLDER: Record<Mode, string> = {
  objects: "예: ZORDER_HDR, ZCL_ORDER_SERVICE (쉼표 구분)",
  ask: "예: 구매요청 승인 로직 고치면 뭐가 영향받아?",
  changes: "예: main..release-2409 (비우면 작업 트리)",
};

const HINT: Record<Mode, string> = {
  objects: "변경한 오브젝트명을 입력합니다. 여러 개는 쉼표로 구분합니다.",
  ask: "업무 용어로 질문하면 대상 오브젝트를 찾아 분석하고, 왜 그 오브젝트를 골랐는지 함께 보여줍니다.",
  changes: "git 리비전 범위의 변경 오브젝트를 자동으로 식별해 분석합니다.",
};

export function ImpactView({ workspace, onAskAgent }: {
  workspace: string | null; onAskAgent: (q: string) => void;
}) {
  const [params, setParams] = useSearchParams();
  const [mode, setMode] = useState<Mode>((params.get("mode") as Mode) ?? "objects");
  const [value, setValue] = useState(params.get("objects") ?? params.get("q") ?? "");
  const [hops, setHops] = useState(3);
  const [report, setReport] = useState<ImpactReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(nextValue = value, nextMode = mode) {
    setBusy(true);
    setError("");
    try {
      const result =
        nextMode === "objects"
          ? await api.impact(nextValue.split(",").map((s) => s.trim()).filter(Boolean), hops, workspace)
          : nextMode === "ask"
            ? await api.ask(nextValue, hops, workspace)
            : await api.changes(nextValue || null, hops, workspace);
      setReport(result);
      setParams({ mode: nextMode, objects: nextValue }, { replace: true });
    } catch (e) {
      setError((e as Error).message);
      setReport(null);
    } finally {
      setBusy(false);
    }
  }

  // A deep link from the dashboard or a Teams card should land on results.
  useEffect(() => {
    const initial = params.get("objects");
    if (initial) void run(initial, (params.get("mode") as Mode) ?? "objects");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <Panel>
        <div className="row">
          <div className="segmented">
            {(["objects", "ask", "changes"] as Mode[]).map((m) => (
              <button key={m} className={mode === m ? "on" : ""}
                      onClick={() => { setMode(m); setValue(""); setReport(null); }}>
                {m === "objects" ? "오브젝트" : m === "ask" ? "업무 용어" : "수정내역"}
              </button>
            ))}
          </div>
          <span className="spacer" />
          <label className="small muted" htmlFor="impact-hops-input">추적 깊이</label>
          <select id="impact-hops-input" value={hops} onChange={(e) => setHops(Number(e.target.value))}>
            {[2, 3, 4, 5].map((h) => <option key={h} value={h}>{h}홉</option>)}
          </select>
        </div>
        <div className="row">
          <input type="text" id="impact-query" className="grow" placeholder={PLACEHOLDER[mode]}
                 value={value} onChange={(e) => setValue(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && void run()} />
          <button className="btn primary" disabled={busy} onClick={() => void run()}>
            {busy ? "분석 중…" : "분석"}
          </button>
        </div>
        <span className="small muted">{HINT[mode]}</span>
      </Panel>

      {error && <ErrorBox message={error} />}
      {!report && !error && !busy && (
        <Empty>분석할 대상을 입력하세요. 대시보드의 참조 집중 오브젝트에서 바로 넘어올 수도 있습니다.</Empty>
      )}
      {report && <ImpactResult report={report} onAskAgent={onAskAgent} />}
    </>
  );
}
