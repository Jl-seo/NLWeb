import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Bar, Empty, ErrorBox, Notice, Panel, StatTile } from "../components/ui";
import type { Dashboard as DashboardData } from "../types";

/**
 * The first question a developer has about an analysis tool is whether to trust
 * it today. So the freshness of the index and the size of its blind spots sit
 * at the top, before any finding.
 */
export function DashboardView({ workspace, onAskAgent }: {
  workspace: string | null; onAskAgent: (q: string) => void;
}) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    setError("");
    api.dashboard(workspace)
      .then((d) => alive && setData(d))
      .catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [workspace]);

  if (error) return <ErrorBox message={error} />;
  if (!data) return <Empty>불러오는 중…</Empty>;

  const maxDependents = Math.max(1, ...data.hotspots.map((h) => h.dependents));

  return (
    <>
      <div className="tiles">
        <StatTile label="개발 오브젝트" value={data.objects.toLocaleString()}
                  note={`${data.type_breakdown.length}개 타입`} />
        <StatTile label="참조 관계" value={data.references.toLocaleString()}
                  note={`미해결 ${data.unresolved.toLocaleString()}건 (표준 오브젝트 등)`} />
        <StatTile label="외부 계약 오브젝트" value={data.external_contract_objects}
                  note="RFC·트랜잭션·서비스 등" />
        <StatTile label="정적 분석 사각지대" value={data.blind_spot_total}
                  note={`${data.blind_spot_objects}개 오브젝트`} warn={data.blind_spot_total > 0} />
      </div>

      <Notice title={data.indexed_at ? `인덱스 기준: ${data.indexed_at}` : "인덱스 시각 미확인"}>
        이 화면의 모든 수치는 위 시점의 코드 스냅샷 기준입니다. 전송 직전이라면 재인덱싱 후 확인하세요.
        {data.unresolved > 0 && ` 미해결 참조 ${data.unresolved}건은 이 코드베이스 밖(표준 SAP 등)을 가리킵니다.`}
      </Notice>

      <Panel title="참조 집중 오브젝트" note="변경 시 파급이 큰 순서"
             actions={
               <button className="btn ghost sm"
                       onClick={() => onAskAgent("참조가 가장 많이 몰린 오브젝트들의 위험을 설명해줘.")}>
                 에이전트에게 묻기
               </button>
             }>
        {data.hotspots.length === 0 ? <Empty>참조 관계가 아직 없습니다.</Empty> : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>오브젝트</th>
                  <th style={{ width: 120 }}>타입</th>
                  <th style={{ width: 190 }}>참조자</th>
                  <th style={{ width: 90 }}>사각지대</th>
                  <th style={{ width: 90 }} />
                </tr>
              </thead>
              <tbody>
                {data.hotspots.map((h) => (
                  <tr key={h.object_key}>
                    <td>
                      <div className="col" style={{ gap: 2 }}>
                        <strong className="mono">{h.object_key}</strong>
                        {h.description && <span className="small muted">{h.description}</span>}
                      </div>
                    </td>
                    <td className="small">{h.object_type_label}</td>
                    <td>
                      <div className="row" style={{ gap: 8 }}>
                        <Bar value={h.dependents} max={maxDependents} />
                        <span className="mono small">{h.dependents}</span>
                      </div>
                    </td>
                    <td className="small">{h.blind_spots || "-"}</td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn sm"
                              onClick={() => navigate(`/impact?objects=${encodeURIComponent(h.object_key)}`)}>
                        영향 분석
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="row" style={{ alignItems: "stretch", gap: 16 }}>
        <div className="grow col">
          <Panel title="최근 변경" note="커밋을 선택하면 코드 리뷰로 이동합니다">
            {data.recent_commits.length === 0 ? (
              <Empty>git 저장소가 아니거나 커밋 이력이 없습니다.</Empty>
            ) : (
              <div className="col" style={{ gap: 0 }}>
                {data.recent_commits.map((c) => (
                  <button key={c.commit} className="file-item"
                          onClick={() => navigate(`/review?rev=${encodeURIComponent(`${c.commit}~1..${c.commit}`)}`)}>
                    <span className="row" style={{ gap: 8 }}>
                      <span className="code-chip">{c.commit}</span>
                      <span className="truncate grow">{c.subject}</span>
                    </span>
                    <span className="small muted">{c.date} · {c.author}</span>
                  </button>
                ))}
              </div>
            )}
          </Panel>
        </div>
        <div style={{ width: 320 }}>
          <Panel title="오브젝트 구성">
            <div className="col" style={{ gap: 7 }}>
              {data.type_breakdown.slice(0, 10).map((t) => (
                <div key={t.type} className="row" style={{ gap: 10 }}>
                  <span className="small grow truncate">{t.label}</span>
                  <div style={{ width: 110 }}>
                    <Bar value={t.count} max={data.type_breakdown[0]?.count ?? 1} />
                  </div>
                  <span className="mono small" style={{ width: 34, textAlign: "right" }}>{t.count}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
