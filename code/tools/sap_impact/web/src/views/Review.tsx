import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { DiffView } from "../components/DiffView";
import { Empty, ErrorBox, EvidenceLine, Panel, SeverityPill } from "../components/ui";
import type { ReviewPayload } from "../types";

/**
 * Review screen: the diff on the left of what it breaks.
 *
 * Files are ordered by how many objects depend on them, not alphabetically,
 * because the file with thirty dependents is the one that decides whether this
 * transport is safe.
 */
export function ReviewView({ workspace, onAskAgent }: {
  workspace: string | null; onAskAgent: (q: string) => void;
}) {
  const [params, setParams] = useSearchParams();
  const [rev, setRev] = useState(params.get("rev") ?? "");
  const [data, setData] = useState<ReviewPayload | null>(null);
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(nextRev = rev) {
    setBusy(true);
    setError("");
    try {
      const payload = await api.review(nextRev || null, 3, workspace);
      setData(payload);
      setActive(0);
      setParams(nextRev ? { rev: nextRev } : {}, { replace: true });
    } catch (e) {
      setError((e as Error).message);
      setData(null);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void run(params.get("rev") ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const file = data?.files[active];

  return (
    <>
      <Panel>
        <div className="row">
          <input type="text" id="review-rev" className="grow"
                 placeholder="git 리비전 범위 (예: main..release-2409, abc123~1..abc123). 비우면 작업 트리"
                 value={rev} onChange={(e) => setRev(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && void run()} />
          <button className="btn primary" disabled={busy} onClick={() => void run()}>
            {busy ? "불러오는 중…" : "리뷰 열기"}
          </button>
        </div>
        {data && (
          <div className="row">
            <span className="small muted grow">
              {data.revision_range} · 파일 {data.files.length}건 · 영향 {data.impact.impacted_count}건
            </span>
            <SeverityPill severity={data.impact.severity} />
            <button className="btn ghost sm"
                    onClick={() => onAskAgent(
                      `${data.revision_range} 변경분을 리뷰해줘. 위험한 부분과 QA가 봐야 할 것을 짚어줘.`)}>
              에이전트 리뷰 요청
            </button>
          </div>
        )}
      </Panel>

      {error && <ErrorBox message={error} />}
      {!data && !error && !busy && <Empty>리뷰할 리비전 범위를 지정하세요.</Empty>}

      {data && (
        <div className="review-grid">
          <Panel title="변경 파일" note="영향 큰 순">
            <div className="col" style={{ gap: 2 }}>
              {data.files.map((f, index) => (
                <button key={f.path} className={`file-item${index === active ? " on" : ""}`}
                        onClick={() => setActive(index)}>
                  <span className="file-name">{f.path.split("/").pop()}</span>
                  <span className="row small muted" style={{ gap: 6 }}>
                    <span>{f.status}</span>
                    <span style={{ color: "var(--add-line)" }}>+{f.added}</span>
                    <span style={{ color: "var(--del-line)" }}>−{f.removed}</span>
                    {f.dependents.length > 0 && <span>· 참조자 {f.dependents.length}</span>}
                    {f.annotations.some((a) => a.severity === "blind") && (
                      <span className="pill MEDIUM" style={{ fontSize: 10 }}>사각지대</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </Panel>

          <div className="col" style={{ gap: 16 }}>
            {file && (
              <>
                <Panel title={file.object_key || file.path}
                       note={[file.object_type_label, file.description].filter(Boolean).join(" · ")}
                       actions={
                         file.object_key ? (
                           <a className="btn sm"
                              href={`/app/impact?objects=${encodeURIComponent(file.object_key)}`}>
                             이 오브젝트 영향 분석
                           </a>
                         ) : undefined
                       }>
                  <span className="small muted">{file.path}</span>
                  {file.dependents.length > 0 ? (
                    <>
                      <span className="small">
                        이 오브젝트를 참조하는 곳 {file.dependents.length}건 — 변경 시 함께 확인해야 합니다.
                      </span>
                      <div className="scroll-x">
                        <table>
                          <tbody>
                            {file.dependents.map((dep) => (
                              <tr key={`${dep.object_key}-${dep.line}`}>
                                <td style={{ width: 230 }}>
                                  <strong className="mono small">{dep.object_key}</strong>
                                  <div className="small muted">{dep.object_type_label}</div>
                                </td>
                                <td>
                                  <EvidenceLine file={dep.file} line={dep.line}
                                                kind={dep.reference_kind} statement={dep.statement} />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : (
                    <span className="small muted">이 코드베이스 안에서 이 오브젝트를 참조하는 곳은 없습니다.</span>
                  )}
                </Panel>

                <Panel title="변경 내용" note="추가된 라인의 위험 구문에 주석이 붙습니다">
                  <DiffView file={file} />
                </Panel>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
