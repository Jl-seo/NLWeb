"""
Service smoke tests. Run from code/:

    SAP_IMPACT_PATH=tools/sap_impact/samples python -m tools.sap_impact.service.test_service

Covers the contract the Foundry agent depends on: every response carries the
evidence needed for citation, and the OpenAPI schema satisfies Foundry's rules
(3.0, server URL present, operationId on every operation).
"""

import json
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "sap_impact.service"

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
os.environ.setdefault("SAP_IMPACT_PATH", SAMPLES)

failures = []


def check(condition, message):
    print(f"  {'PASS' if condition else 'FAIL'}  {message}")
    if not condition:
        failures.append(message)


def main() -> int:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("fastapi 가 설치되어 있지 않습니다: pip install -r service/requirements.txt")
        return 2

    from .app import app, registry
    from .export_openapi import build

    registry.reindex("default", background=False)
    client = TestClient(app)

    print("[서비스]")
    check(client.get("/health").json()["status"] == "ok", "health 응답")
    workspaces = client.get("/workspaces").json()
    check(workspaces[0]["ready"] and workspaces[0]["objects"] > 10, "workspace 인덱싱 완료")

    print("\n[영향 분석 API]")
    impact = client.post("/impact", json={"objects": ["ZORDER_HDR"], "hops": 4}).json()
    check(impact["severity"] == "HIGH", f"DDIC 테이블 변경 위험도 ({impact['severity']})")
    check(impact["impacted_count"] >= 6, f"영향 오브젝트 {impact['impacted_count']}건")
    check(all(i["evidence"]["file"] and i["evidence"]["line"] for i in impact["impacted"]),
          "모든 영향 항목에 파일·라인 근거 포함")
    check(any(i["object_key"] == "TRAN/ZORDER" for i in impact["impacted"]), "트랜잭션까지 도달")
    check(impact["external_contracts"], "외부 계약 도달 보고")
    check(impact["blind_spots"], "사각지대 보고")
    check(impact["regression_scope"], "회귀 테스트 범위 제시")

    print("\n[프롬프트 API]")
    ask = client.post("/ask", json={"prompt": "구매요청 승인 로직 고치면 뭐가 영향받아?",
                                    "select": 1}).json()
    check("PROG/ZMM_PR_APPROVE" in ask["changed_objects"],
          f"트랜잭션 선택 시 배후 프로그램까지 확장 ({ask['changed_objects']})")
    check(ask["resolved_from_prompt"][0]["matched_because"], "선택 근거 제공")

    print("\n[사용처 API]")
    used = client.get("/where-used", params={"object": "ZCL_ORDER_SERVICE"}).json()
    check(used["object"]["direct_dependents"] >= 1, "직접 참조자 수 제공")
    check(used["used_by"][0]["evidence"]["statement"], "사용처 근거 구문 제공")

    print("\n[오류 처리]")
    check(client.post("/impact", json={"objects": ["ZNOPE"]}).json()["not_found"] == ["ZNOPE"],
          "없는 오브젝트는 not_found 로 보고")
    check(client.post("/ask", json={"prompt": "존재하지않는업무용어xyz"}).status_code == 404,
          "검색 실패 시 404")

    print("\n[Foundry OpenAPI 스키마]")
    spec = build("https://example.azurewebsites.net", api_key_header=True)
    check(spec["openapi"].startswith("3.0"), f"OpenAPI 3.0 ({spec['openapi']})")
    check(spec["servers"][0]["url"].startswith("https://"), "server URL 포함")
    ops = [op for methods in spec["paths"].values() for op in methods.values()]
    check(all(op.get("operationId") for op in ops), f"operationId 전수 존재 ({len(ops)}건)")
    check(spec["components"]["securitySchemes"]["apiKeyHeader"]["name"] == "x-api-key",
          "API 키 보안 스키마")
    check('"type": [' not in json.dumps(spec), "3.1 전용 타입 배열 제거됨")

    print()
    if failures:
        print(f"실패 {len(failures)}건")
        return 1
    print("전체 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
