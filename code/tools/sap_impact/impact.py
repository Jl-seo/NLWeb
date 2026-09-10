"""
Impact assessment: turn graph reachability into a reviewable risk statement.

Scoring is deliberately rule-based and printed with its reasons, so a customer
can argue with the rules instead of arguing with a black box. The LLM layer adds
narrative on top of this; it never changes the numbers.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import model as M
from .graph import Graph, Hit
from .model import CodeBase

SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# Edge kinds that carry a stronger coupling than a mere type reference.
STRONG_KINDS = {
    "CALL_FUNCTION", "SUBMIT", "PERFORM_EXT", "INHERITS", "IMPLEMENTS",
    "WRITE", "CALL_TRANSACTION", "CDS_FROM", "CDS_EXTEND", "BELONGS_TO",
    "UI5_CONTROLLER_BIND", "CAP_HANDLER_BIND", "ODATA_SOURCE",
}


@dataclass
class ImpactReport:
    changed: List[str]
    missing: List[str] = field(default_factory=list)
    impacted: List[Hit] = field(default_factory=list)
    depends_on: List[Hit] = field(default_factory=list)
    severity: str = "LOW"
    reasons: List[str] = field(default_factory=list)
    blind_spots: List[Dict[str, Any]] = field(default_factory=list)
    external_contracts: List[str] = field(default_factory=list)
    test_scope: List[str] = field(default_factory=list)
    max_hops: int = 3

    def to_dict(self, cb: CodeBase) -> Dict[str, Any]:
        return {
            "changed": self.changed,
            "missing": self.missing,
            "severity": self.severity,
            "reasons": self.reasons,
            "impacted_count": len(self.impacted),
            "impacted": [
                {
                    "key": h.key,
                    "type": cb.objects[h.key].obj_type if h.key in cb.objects else M.UNKNOWN,
                    "hops": h.hops,
                    "path": list(h.via),
                    "edge_kinds": list(h.kinds),
                    "trigger": h.edge.snippet if h.edge else "",
                    "trigger_file": (cb.objects[h.edge.source].paths[:1]
                                     if h.edge and h.edge.source in cb.objects else []),
                    "trigger_line": h.edge.line if h.edge else 0,
                }
                for h in self.impacted
            ],
            "depends_on": [{"key": h.key, "hops": h.hops, "kind": h.kinds[-1] if h.kinds else ""}
                           for h in self.depends_on],
            "external_contracts": self.external_contracts,
            "blind_spots": self.blind_spots,
            "test_scope": self.test_scope,
        }


def analyze(cb: CodeBase, graph: Graph, changed_keys: List[str],
            max_hops: int = 3, include_forward: bool = True) -> ImpactReport:
    present = [k for k in changed_keys if k in cb.objects]
    missing = [k for k in changed_keys if k not in cb.objects]

    report = ImpactReport(changed=present, missing=missing, max_hops=max_hops)
    if not present:
        report.reasons.append("변경 오브젝트를 코드베이스에서 찾지 못했습니다.")
        return report

    report.impacted = graph.impacted_by(present, max_hops=max_hops)
    if include_forward:
        report.depends_on = graph.depends_on(present, max_hops=2)

    _score(cb, graph, report)
    _collect_blind_spots(cb, report)
    _build_test_scope(cb, report)
    return report


def _score(cb: CodeBase, graph: Graph, report: ImpactReport) -> None:
    score = 0
    direct = [h for h in report.impacted if h.hops == 1]

    if len(report.impacted) >= 30:
        score += 3
        report.reasons.append(f"영향 오브젝트 {len(report.impacted)}건 — 광범위 회귀 위험")
    elif len(report.impacted) >= 10:
        score += 2
        report.reasons.append(f"영향 오브젝트 {len(report.impacted)}건")
    elif report.impacted:
        score += 1
        report.reasons.append(f"영향 오브젝트 {len(report.impacted)}건 (직접 참조 {len(direct)}건)")
    else:
        report.reasons.append("이 코드베이스 내 참조자 없음 — 국소 변경")

    for key in report.changed:
        obj = cb.objects[key]
        if obj.obj_type in M.DATA_LAYER_TYPES:
            score += 2
            report.reasons.append(
                f"{M.type_label(obj.obj_type)} 변경 — 필드 추가/타입 변경 시 테이블 컨버전 및 "
                f"기존 데이터 영향 검토 필요 ({obj.name})")
        if obj.obj_type in M.EXTERNAL_CONTRACT_TYPES:
            score += 2
            report.reasons.append(f"외부 인터페이스 오브젝트 변경 — 연계 시스템 계약 영향 ({obj.name})")
        if "RFC" in obj.tags:
            score += 1
            report.reasons.append(f"{obj.name}: 원격 호출(RFC/DESTINATION) 포함 — 타 시스템 연계")
        if "UPDATE_TASK" in obj.tags or "COMMIT_WORK" in obj.tags:
            score += 1
            report.reasons.append(f"{obj.name}: 업데이트 태스크/COMMIT 포함 — 트랜잭션 일관성 검증 필요")

    externals = []
    for hit in report.impacted:
        obj = cb.objects.get(hit.key)
        if obj and obj.obj_type in M.EXTERNAL_CONTRACT_TYPES:
            externals.append(hit.key)
    if externals:
        score += 2
        report.external_contracts = externals
        report.reasons.append(
            f"영향 범위가 외부 계약 오브젝트 {len(externals)}건에 도달 "
            f"(예: {', '.join(externals[:3])})")

    strong = [h for h in report.impacted if h.kinds and h.kinds[-1] in STRONG_KINDS]
    if len(strong) >= 5:
        score += 1
        report.reasons.append(f"강결합 참조(호출·상속·쓰기) {len(strong)}건")

    hot = [k for k in report.changed if graph.fan_in(k) >= 10]
    if hot:
        score += 1
        report.reasons.append(f"고참조 오브젝트 변경: {', '.join(hot)} (fan-in ≥ 10)")

    report.severity = SEVERITY_ORDER[min(score // 2, len(SEVERITY_ORDER) - 1)]


def _collect_blind_spots(cb: CodeBase, report: ImpactReport) -> None:
    scope = set(report.changed) | {h.key for h in report.impacted}
    for key, spots in cb.blind_spots.items():
        if key in scope:
            for spot in spots:
                report.blind_spots.append({"object": key, **spot})
    if report.blind_spots:
        report.reasons.append(
            f"정적 분석 사각지대 {len(report.blind_spots)}건 (동적 호출) — "
            "그래프에 안 잡히는 호출 경로가 있으므로 수동 확인 필요")


def _build_test_scope(cb: CodeBase, report: ImpactReport) -> None:
    """
    Regression scope a tester can act on: things a person can actually execute --
    transactions, reports, services, UI5 views -- rather than the raw object list.
    """
    runnable_types = {M.TRANSACTION, M.PROGRAM, M.CAP_SERVICE, M.SERVICE_BINDING,
                      M.UI5_VIEW, M.FUNCTION_MODULE}
    for hit in report.impacted:
        obj = cb.objects.get(hit.key)
        if obj and obj.obj_type in runnable_types:
            label = f"{M.type_label(obj.obj_type)} {obj.name}"
            if obj.description:
                label += f" ({obj.description})"
            if label not in report.test_scope:
                report.test_scope.append(label)
