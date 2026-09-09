import { useEffect, useMemo, useState } from "react";
import type { ImpactReport } from "../types";
import { ImpactGraph } from "./ImpactGraph";
import { Bar, Empty, EvidenceLine, Notice, Panel, SeverityPill } from "./ui";

type SortKey = "hops" | "object_key" | "object_type_label";

export function ImpactResult({ report, onAskAgent }: {
  report: ImpactReport; onAskAgent?: (question: string) => void;
}) {
  const [filter, setFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [maxHops, setMaxHops] = useState(0);
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: "hops", asc: true });
  const [selected, setSelected] = useState<string | null>(null);

  const types = useMemo(
    () => [...new Set(report.impacted.map((i) => i.object_type_label))].sort(),
    [report],
  );

  const rows = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const list = report.impacted.filter((item) => {
      if (typeFilter && item.object_type_label !== typeFilter) return false;
      if (maxHops && item.hops > maxHops) return false;
      if (!needle) return true;
      return `${item.object_key} ${item.description} ${item.evidence.file} ${item.evidence.statement}`
        .toLowerCase().includes(needle);
    });
    return [...list].sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const cmp = av > bv ? 1 : av < bv ? -1 : 0;
      return cmp * (sort.asc ? 1 : -1);
    });
  }, [report, filter, typeFilter, maxHops, sort]);

  const toggleSort = (key: SortKey) =>
    setSort((s) => ({ key, asc: s.key === key ? !s.asc : true }));

  return (
    <>
      <Panel>
        <div className="row">
          <div className="col grow" style={{ gap: 4 }}>
            <div className="row" style={{ gap: 6 }}>
              {report.changed_objects.map((key) => (
                <span key={key} className="code-chip">{key}</span>
              ))}
              {!report.changed_objects.length && <span className="muted">분석 대상 없음</span>}
            </div>
            <span className="small muted">
              영향 {report.impacted_count}건
              {report.truncated && ` (표시 ${report.impacted.length}건)`}
              {report.external_contracts.length > 0 &&
                ` · 외부 계약 ${report.external_contracts.length}건 도달`}
            </span>
          </div>
          <SeverityPill severity={report.severity} />
        </div>

        <ul className="col small" style={{ margin: 0, paddingLeft: 18, gap: 3 }}>
          {report.severity_reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>

        {report.not_found.length > 0 && (
          <span className="small muted">코드베이스에서 못 찾음: {report.not_found.join(", ")}</span>
        )}

        {onAskAgent && report.changed_objects.length > 0 && (
          <div className="suggestions">
            <button className="suggestion"
                    onClick={() => onAskAgent(
                      `${report.changed_objects.join(", ")} 변경의 업무 영향을 설명하고, 이행 시 주의사항을 알려줘.`)}>
              에이전트에게 설명 요청
            </button>
            <button className="suggestion"
                    onClick={() => onAskAgent(
                      `${report.changed_objects.join(", ")} 변경에 대해 회귀 테스트 계획을 세워줘.`)}>
              테스트 계획 요청
            </button>
          </div>
        )}
      </Panel>

      {report.resolved_from_prompt.length > 0 && (
        <Panel title="대상 선택 근거" note="질문에서 이 오브젝트를 고른 이유">
          <table>
            <tbody>
              {report.resolved_from_prompt.map((c) => (
                <tr key={c.object_key}>
                  <td style={{ width: 220 }}><code>{c.object_key}</code></td>
                  <td className="muted small">{c.matched_because}</td>
                  <td className="small" style={{ width: 60, textAlign: "right" }}>{c.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {report.impacted.length > 0 && (
        <Panel title="영향 경로" note="변경 지점에서 몇 홉 떨어져 있는지, 무엇을 거쳐 도달하는지">
          <ImpactGraph report={report} onSelect={setSelected} />
          {selected && (
            <div className="small">
              선택: <code>{selected}</code>{" "}
              <button className="btn ghost sm" onClick={() => { setFilter(selected); setSelected(null); }}>
                아래 목록에서 보기
              </button>
            </div>
          )}
        </Panel>
      )}

      <Panel
        title="영향 오브젝트"
        note={`${rows.length}건 표시`}
        actions={
          <div className="row" style={{ gap: 6 }}>
            <input type="text" id="impact-filter" placeholder="오브젝트·근거 검색"
                   value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 180 }} />
            <select id="impact-type" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">전체 타입</option>
              {types.map((t) => <option key={t}>{t}</option>)}
            </select>
            <select id="impact-hops" value={maxHops}
                    onChange={(e) => setMaxHops(Number(e.target.value))}>
              <option value={0}>전체 홉</option>
              {[1, 2, 3, 4, 5].map((h) => <option key={h} value={h}>{h}홉 이내</option>)}
            </select>
            <button className="btn sm" onClick={() => downloadCsv(report)}>CSV</button>
          </div>
        }
      >
        {rows.length === 0 ? (
          <Empty>조건에 맞는 항목이 없습니다.</Empty>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 52 }} onClick={() => toggleSort("hops")}>홉</th>
                  <th onClick={() => toggleSort("object_key")}>오브젝트</th>
                  <th style={{ width: 130 }} onClick={() => toggleSort("object_type_label")}>타입</th>
                  <th style={{ width: "42%" }}>근거</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => (
                  <tr key={item.object_key}>
                    <td className="mono">{item.hops}</td>
                    <td>
                      <div className="col" style={{ gap: 2 }}>
                        <strong className="mono">{item.object_key}</strong>
                        {item.description && <span className="small muted">{item.description}</span>}
                        <span className="small muted">{item.path.join(" → ")}</span>
                      </div>
                    </td>
                    <td className="small">{item.object_type_label}</td>
                    <td>
                      <EvidenceLine file={item.evidence.file} line={item.evidence.line}
                                    kind={item.evidence.reference_kind}
                                    statement={item.evidence.statement} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {report.external_contracts.length > 0 && (
        <Panel title="외부 계약 도달" note="연계 시스템·사용자 화면에 노출되는 지점">
          <div className="row" style={{ gap: 6 }}>
            {report.external_contracts.map((key) => (
              <span key={key} className="pill HIGH">{key}</span>
            ))}
          </div>
          <span className="small muted">이행 시 통보 대상입니다.</span>
        </Panel>
      )}

      {report.regression_scope.length > 0 && (
        <RegressionChecklist report={report} />
      )}

      {report.blind_spots.length > 0 && (
        <Panel title={`정적 분석 사각지대 ${report.blind_spots.length}건`}>
          <Notice title="이 목록은 완전하지 않습니다">
            동적 호출은 코드만으로 추적할 수 없습니다. 아래 지점은 담당자 확인이 필요합니다.
          </Notice>
          <table>
            <tbody>
              {report.blind_spots.map((spot, i) => (
                <tr key={`${spot.object_key}-${spot.line}-${i}`}>
                  <td style={{ width: 220 }}><code>{spot.object_key}</code></td>
                  <td><span className="code-chip">{spot.file}:{spot.line}</span></td>
                  <td className="small">{spot.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </>
  );
}

/** Test progress is state a person owns, so it survives reloads per change set. */
function RegressionChecklist({ report }: { report: ImpactReport }) {
  const storageKey = `sap-impact:tests:${report.workspace}:${report.changed_objects.join(",")}`;
  const [done, setDone] = useState<number[]>([]);

  useEffect(() => {
    try {
      setDone(JSON.parse(localStorage.getItem(storageKey) ?? "[]") as number[]);
    } catch {
      setDone([]);
    }
  }, [storageKey]);

  const toggle = (index: number) => {
    const next = done.includes(index) ? done.filter((i) => i !== index) : [...done, index];
    setDone(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      /* private mode: progress simply is not remembered */
    }
  };

  const total = report.regression_scope.length;
  return (
    <Panel title="회귀 테스트 범위" note={`${done.length}/${total} 완료`}
           actions={<div style={{ width: 120 }}><Bar value={done.length} max={total} /></div>}>
      <div className="col" style={{ gap: 6 }}>
        {report.regression_scope.map((item, index) => (
          <label key={item} className="row" style={{ gap: 8, cursor: "pointer" }}>
            <input type="checkbox" id={`test-${index}`} checked={done.includes(index)}
                   onChange={() => toggle(index)} />
            <span className={done.includes(index) ? "muted" : ""}
                  style={{ textDecoration: done.includes(index) ? "line-through" : "none" }}>
              {item}
            </span>
          </label>
        ))}
      </div>
    </Panel>
  );
}

function downloadCsv(report: ImpactReport) {
  const head = ["홉", "오브젝트", "타입", "설명", "참조경로", "근거파일", "근거라인", "참조종류", "근거구문"];
  const rows = report.impacted.map((i) => [
    i.hops, i.object_key, i.object_type_label, i.description, i.path.join(" > "),
    i.evidence.file, i.evidence.line, i.evidence.reference_kind, i.evidence.statement,
  ]);
  const csv = [head, ...rows]
    .map((cols) => cols.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\r\n");
  // BOM so Excel reads the Korean columns as UTF-8.
  const blob = new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `sap-impact-${report.changed_objects[0]?.replace(/\W/g, "_") ?? "result"}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}
