"""
Smoke tests over samples/. Run: python -m tools.sap_impact.test_sap_impact

The repository has no test runner configured, so these are plain assertions
executable with the standard interpreter. They pin the edges that matter: if a
regex change silently stops finding SELECT statements, the impact analysis would
under-report, which is the one failure mode a customer must never hit.
"""

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "sap_impact"

from . import model as M
from .graph import Graph
from .impact import analyze
from .scanner import scan
from .search import resolve

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

failures = []


def check(condition, message):
    if condition:
        print(f"  PASS  {message}")
    else:
        print(f"  FAIL  {message}")
        failures.append(message)


def main() -> int:
    cb = scan(SAMPLES)
    graph = Graph(cb)
    keys = set(cb.objects)

    print("[분류]")
    for expected in ("TABL/ZORDER_HDR", "CLAS/ZCL_ORDER_SERVICE", "INTF/ZIF_ORDER_HANDLER",
                     "FUNC/ZFM_ORDER_POST", "FUGR/ZFG_ORDER", "PROG/ZMM_PR_APPROVE",
                     "DDLS/ZI_ORDER", "TRAN/ZORDER", "DTEL/ZDE_ORDER_ID",
                     "CAP_SRV/OrderService", "UI5_VIEW/view.Order", "UI5_CTRL/controller.Order"):
        check(expected in keys, f"{expected} 분류됨")
    check(not any(k.startswith("VIEW/ORDER") for k in keys),
          "UI5 뷰가 DDIC 뷰로 오분류되지 않음")

    print("\n[참조 추출]")
    edges = {(r.source, r.target, r.kind) for r in cb.references}
    for edge in (
        ("CLAS/ZCL_ORDER_SERVICE", "TABL/ZORDER_HDR", "SELECT"),
        ("CLAS/ZCL_ORDER_SERVICE", "INTF/ZIF_ORDER_HANDLER", "IMPLEMENTS"),
        ("CLAS/ZCL_ORDER_SERVICE", "FUNC/ZFM_ORDER_POST", "CALL_FUNCTION"),
        ("FUNC/ZFM_ORDER_POST", "TABL/ZORDER_HDR", "WRITE"),
        ("FUNC/ZFM_ORDER_POST", "FUGR/ZFG_ORDER", "BELONGS_TO"),
        ("PROG/ZMM_PR_APPROVE", "CLAS/ZCL_ORDER_SERVICE", "NEW"),
        ("PROG/ZMM_PR_APPROVE", "PROG/ZMM_PR_PRINT", "SUBMIT"),
        ("DDLS/ZI_ORDER", "TABL/ZORDER_HDR", "CDS_FROM"),
        ("TRAN/ZORDER", "PROG/ZMM_PR_APPROVE", "TRANSACTION_PROGRAM"),
        ("CAP_SRV/OrderService", "CAP_ENTITY/db.schema", "CDS_USING"),
        ("UI5_VIEW/view.Order", "UI5_CTRL/controller.Order", "UI5_CONTROLLER_BIND"),
        ("UI5_MANIFEST/manifest", "CAP_SRV/OrderService", "ODATA_SOURCE"),
    ):
        check(edge in edges, f"{edge[0]} -{edge[2]}-> {edge[1]}")

    print("\n[영향 분석]")
    report = analyze(cb, graph, ["TABL/ZORDER_HDR"], max_hops=4)
    impacted = {h.key for h in report.impacted}
    check("PROG/ZMM_PR_APPROVE" in impacted, "테이블 변경이 리포트에 도달")
    check("TRAN/ZORDER" in impacted, "테이블 변경이 트랜잭션까지 2홉 도달")
    check(report.severity in ("HIGH", "CRITICAL"), f"DDIC 테이블 변경 위험도 상향 ({report.severity})")
    check("TRAN/ZORDER" in report.external_contracts, "외부 계약 오브젝트 식별")
    check(any("동적" in b["reason"] for b in report.blind_spots), "동적 호출 사각지대 보고")

    print("\n[국소 변경]")
    local = analyze(cb, graph, ["UI5_MOD/model.formatter"], max_hops=3)
    check(local.severity == "LOW", f"참조자 적은 변경은 낮은 위험도 ({local.severity})")

    print("\n[프롬프트 해석]")
    hits = [c.key for c in resolve(cb, "구매요청 승인 로직 고치면 뭐가 영향받아?", limit=5)]
    check("TRAN/ZORDER" in hits[:2], f"업무 용어로 오브젝트 검색 (상위: {hits[:2]})")

    print("\n[장애 역추적]")
    from .incident import trace
    inc = trace(cb, graph, "ZORDER 트랜잭션 오류", since="3650 days ago")
    check(any(o["object_key"] == "TRAN/ZORDER" for o in inc.symptom_objects), "증상이 트랜잭션으로 해석")
    check(inc.commits_in_window >= 1, f"기간 내 커밋 {inc.commits_in_window}건 수집")
    check(inc.candidates and inc.candidates[0].commits[0]["commit"], "후보에 커밋 메타데이터")
    check(any(c.hops == 0 for c in inc.candidates), "증상 오브젝트 자체 변경이 0홉 후보")
    check(all(c.path[0] in [o["object_key"] for o in inc.symptom_objects] or c.hops == 0
              for c in inc.candidates), "경로가 증상 오브젝트에서 시작")
    check(inc.blind_spots_on_path and any("원인일 수 있" in n for n in inc.notes),
          "경로상 동적 호출을 사각지대로 경고")
    empty = trace(cb, graph, "존재하지않는증상xyz", since="3650 days ago")
    check(not empty.candidates and empty.notes, "해석 불가 증상은 안내와 함께 빈 결과")

    print("\n[기간 요약]")
    from .summary import summarize
    period = summarize(cb, graph, since="3650 days ago")
    check(period.commits >= 1 and period.commits_with_sap_objects >= 1, "커밋 집계")
    check(sum(period.by_severity.values()) == period.commits_with_sap_objects, "위험도 분포 합계 일치")
    check(period.high_risk and period.high_risk[0].changed_objects, "고위험 커밋에 변경 오브젝트")
    check(any(h["object_key"] == "TABL/ZORDER_HDR" for h in period.hotspots_touched),
          "핫스팟 변경 감지")
    none = summarize(cb, graph, since="2050-01-01")  # git 날짜 파서 범위 안의 미래
    check(none.commits == 0 and none.notes, "커밋 없는 기간은 안내")

    print("\n[사각지대 미보고 방지]")
    check(cb.blind_spots, "동적 호출이 사각지대로 수집됨")

    print()
    if failures:
        print(f"실패 {len(failures)}건")
        return 1
    print("전체 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
