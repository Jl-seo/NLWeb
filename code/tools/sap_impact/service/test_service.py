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

    print("\n[Adaptive Card]")
    card_response = client.post("/cards/impact", json={"objects": ["ZORDER_HDR"], "hops": 4}).json()
    card = card_response["content"]
    check(card_response["contentType"] == "application/vnd.microsoft.card.adaptive",
          "Teams 카드 contentType")
    check(card["version"] == "1.5" and card["type"] == "AdaptiveCard", "Adaptive Card 1.5")
    rendered = json.dumps(card, ensure_ascii=False)
    check("위험도 높음" in rendered, "위험도 배지 포함")
    check("사각지대" in rendered, "사각지대 경고 포함")
    check("ZFM_ORDER_POST" in rendered, "영향 오브젝트 인용 포함")
    check(bool(card.get("actions")), "탭으로 이동하는 액션 포함")
    empty = client.post("/cards/impact", json={})
    check(empty.status_code == 400, "대상 없이 카드 요청 시 400")

    print("\n[대시보드 API]")
    dash = client.get("/dashboard").json()
    check(dash["objects"] > 10 and dash["references"] > 10, "코드베이스 규모 집계")
    check(bool(dash["indexed_at"]), "인덱스 시각 제공 — 신뢰성 판단 근거")
    check(dash["hotspots"] and dash["hotspots"][0]["dependents"] >= 5, "참조 집중 오브젝트 순위")
    check(dash["blind_spot_total"] >= 1, "사각지대 집계")
    check(dash["external_contract_objects"] >= 1, "외부 계약 오브젝트 집계")

    print("\n[코드 리뷰 API]")
    sample_file = os.path.join(SAMPLES, "src", "zcl_order_service.clas.abap")
    original = open(sample_file, encoding="utf-8").read()
    try:
        with open(sample_file, "w", encoding="utf-8") as fh:
            fh.write(original.replace(
                "    mv_last_id = iv_order_id.",
                "    mv_last_id = iv_order_id.\n"
                "    UPDATE zorder_hdr SET status = 'P' WHERE order_id = @iv_order_id.\n"
                "    CALL FUNCTION lv_dynamic.\n"
                "    COMMIT WORK."))
        res = client.post("/review", json={"hops": 3})
        if res.status_code != 200:
            check(False, f"리뷰 응답 {res.status_code} {res.text[:80]}")
        else:
            review = res.json()
            target = next((f for f in review["files"] if f["object_key"] == "CLAS/ZCL_ORDER_SERVICE"), None)
            check(target is not None, "변경 파일이 오브젝트로 매핑됨")
            if target:
                labels = {a["label"] for a in target["annotations"]}
                check("DB 쓰기 추가" in labels, "추가된 DB 쓰기 라인 주석")
                check("정적 분석 사각지대" in labels, "동적 호출 라인이 사각지대로 주석")
                check("트랜잭션 확정/취소" in labels, "COMMIT WORK 라인 주석")
                check(all(a["line"] > 0 for a in target["annotations"]), "주석에 라인 번호 존재")
                check(target["added"] >= 3 and target["hunks"], "diff 파싱")
                check(target["dependents"] and target["dependents"][0]["statement"],
                      "변경 오브젝트의 참조자와 근거 구문")
            check(review["impact"]["severity"] in ("MEDIUM", "HIGH", "CRITICAL"),
                  f"리뷰 대상 위험도 ({review['impact']['severity']})")
    finally:
        with open(sample_file, "w", encoding="utf-8") as fh:
            fh.write(original)

    print("\n[웹 앱 서빙]")
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webdist")
    if os.path.isdir(web_dir):
        index = client.get("/app/")
        check(index.status_code == 200 and "<div id=\"root\">" in index.text, "React 앱 index 서빙")
        deep = client.get("/app/review")
        check(deep.status_code == 200 and "<div id=\"root\">" in deep.text,
              "딥링크가 SPA fallback 으로 처리됨")
        check(client.get("/", follow_redirects=False).status_code in (302, 307), "/ 리다이렉트")
    else:
        print("  SKIP  webdist 없음 — cd web && npm install && npm run build 후 재실행")

    print("\n[에이전트]")
    status = client.get("/agent/status").json()
    check("configured" in status and "agent_name" in status, "에이전트 설정 상태 조회")

    print("\n[Teams 앱 패키지]")
    import subprocess
    import sys as _sys
    import tempfile
    import uuid
    import zipfile
    teams_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "teams_app")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "pkg.zip")
        proc = subprocess.run(
            [_sys.executable, os.path.join(teams_dir, "build_package.py"),
             "--host", "sap-impact.example.com", "--app-id", str(uuid.uuid4()),
             "--developer", "테스트", "--bot-id", str(uuid.uuid4()), "--out", out],
            capture_output=True, text=True)
        check(proc.returncode == 0, f"패키지 빌드 성공 {proc.stderr.strip()[:80]}")
        if proc.returncode == 0:
            with zipfile.ZipFile(out) as zf:
                names = set(zf.namelist())
                manifest = json.loads(zf.read("manifest.json"))
            check(names == {"manifest.json", "color.png", "outline.png"}, "패키지 구성 파일")
            check("${{" not in json.dumps(manifest), "치환되지 않은 플레이스홀더 없음")
            check(manifest["staticTabs"][0]["contentUrl"].endswith("/app/"),
                  "개인 탭이 React 앱을 가리킴")
            check(manifest["configurableTabs"][0]["configurationUrl"].endswith("/app/config"),
                  "채널 탭 설정 URL")
            check("bots" in manifest and "composeExtensions" in manifest, "봇·메시지 확장 포함")
            check(manifest["validDomains"] == ["sap-impact.example.com"], "validDomains 설정")
        bad = subprocess.run(
            [_sys.executable, os.path.join(teams_dir, "build_package.py"),
             "--host", "https://x.com", "--app-id", str(uuid.uuid4()), "--out", out],
            capture_output=True, text=True)
        check(bad.returncode != 0, "스킴 포함 host 는 빌드 거부")

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
