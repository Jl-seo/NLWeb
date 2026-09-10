import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, EvidenceLine, Panel } from "../components/ui";
import type { ObjectSummary, WhereUsed } from "../types";

/** Object lookup and where-used: the SE84 question, answered with evidence. */
export function ExploreView({ workspace }: { workspace: string | null }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ObjectSummary[]>([]);
  const [detail, setDetail] = useState<WhereUsed | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function search() {
    if (!query.trim()) return;
    setBusy(true);
    setError("");
    try {
      setResults(await api.search(query, workspace));
      setDetail(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function open(key: string) {
    setBusy(true);
    try {
      setDetail(await api.whereUsed(key, workspace));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Panel>
        <div className="row">
          <input type="text" id="explore-query" className="grow"
                 placeholder="오브젝트명 또는 업무 용어 (예: ZORDER, 구매오더)"
                 value={query} onChange={(e) => setQuery(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && void search()} />
          <button className="btn primary" disabled={busy} onClick={() => void search()}>검색</button>
        </div>
      </Panel>

      {error && <ErrorBox message={error} />}

      {results.length > 0 && (
        <Panel title="검색 결과" note={`${results.length}건`}>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>오브젝트</th>
                  <th style={{ width: 130 }}>타입</th>
                  <th style={{ width: 90 }}>참조자</th>
                  <th style={{ width: 100 }} />
                </tr>
              </thead>
              <tbody>
                {results.map((item) => (
                  <tr key={item.object_key}>
                    <td>
                      <strong className="mono">{item.object_key}</strong>
                      {item.description && <div className="small muted">{item.description}</div>}
                      {item.tags.length > 0 && (
                        <div className="row small" style={{ gap: 4, marginTop: 3 }}>
                          {item.tags.map((t) => <span key={t} className="pill neutral">{t}</span>)}
                        </div>
                      )}
                    </td>
                    <td className="small">{item.object_type_label}</td>
                    <td className="mono small">{item.direct_dependents}</td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn sm" onClick={() => void open(item.object_key)}>사용처</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {detail && (
        <Panel title={`${detail.object.object_key} 사용처`}
               note={`${detail.used_by.length}곳에서 참조 · 이 오브젝트는 ${detail.uses.length}개를 사용`}
               actions={
                 <a className="btn sm"
                    href={`/app/impact?objects=${encodeURIComponent(detail.object.object_key)}`}>
                   영향 분석
                 </a>
               }>
          {detail.used_by.length === 0 ? <Empty>참조하는 곳이 없습니다.</Empty> : (
            <div className="scroll-x">
              <table>
                <tbody>
                  {detail.used_by.map((use) => (
                    <tr key={`${use.object_key}-${use.evidence.line}`}>
                      <td style={{ width: 240 }}>
                        <strong className="mono small">{use.object_key}</strong>
                        <div className="small muted">{use.object_type_label}</div>
                      </td>
                      <td>
                        <EvidenceLine file={use.evidence.file} line={use.evidence.line}
                                      kind={use.evidence.reference_kind}
                                      statement={use.evidence.statement} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}

      {!results.length && !detail && !error && (
        <Empty>오브젝트명이나 업무 용어로 검색하세요.</Empty>
      )}
    </>
  );
}
