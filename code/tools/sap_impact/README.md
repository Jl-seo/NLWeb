# SAP 변경 영향 분석 (sap_impact)

SAP 개발 코드가 저장된 디렉토리를 주면, **무엇이 영향받는지**를 참조 그래프로 계산하고
**왜·얼마나 위험한지**를 LLM이 설명하는 CLI 도구입니다.

## 왜 2계층인가

"디렉토리를 통째로 LLM에 넣고 영향도를 물어본다"는 접근은 두 가지 이유로 실패합니다.
수만 개 오브젝트가 컨텍스트에 들어가지 않고, 모델이 존재하지 않는 오브젝트명을 그럴듯하게
지어냅니다. 영향 분석은 한 번만 틀려도 신뢰를 잃습니다.

| 계층 | 담당 | 구현 |
|---|---|---|
| ① 결정론적 참조 그래프 | **무엇이** 영향받는가 (사실) | `scanner.py`, `extract_abap.py`, `extract_btp.py`, `graph.py` |
| ② 규칙 기반 위험도 | **얼마나** 위험한가 (재현 가능한 판정) | `impact.py` |
| ③ LLM 설명 | **왜**, 무엇을 테스트해야 하는가 (해석) | `explain.py` |

①의 모든 엣지는 파일·라인·원본 구문을 근거로 가지고 있습니다. ③은 ①이 만든 **닫힌 목록만**
보며, 목록에 없는 오브젝트명을 만들어내지 말라는 제약을 프롬프트에 명시합니다.

## 지원 범위

- **abapGit export** — 파일명 규칙(`zcl_x.clas.abap`, `zfg_y.fugr.zfm_z.abap`, `ztab.tabl.xml`)으로
  오브젝트 타입을 결정론적으로 분류. 클래스/인터페이스/프로그램/인클루드/펑션그룹/펑션모듈/
  DDIC(테이블·구조·데이터엘리먼트·도메인·테이블타입)/CDS/트랜잭션/메시지클래스/인핸스먼트 등
- **SE38/SE80 텍스트 덤프** — 파일명 규칙이 없으면 소스 헤더(`REPORT`, `FUNCTION-POOL`,
  `CLASS ... DEFINITION`)로 타입 추론
- **SAP BTP / CAP / Fiori** — CAP CDS(`using`, `projection on`), 서비스 핸들러(JS/TS),
  UI5(manifest routing, `controllerName`, fragment, `sap.ui.define` 의존성)
- **ABAP → CDS → OData → UI5** 경로가 하나의 그래프로 연결됩니다. 수작업 영향 분석이 가장 자주
  놓치는 구간입니다.

추출하는 ABAP 참조: `CALL FUNCTION`, `PERFORM ... IN PROGRAM`, `SUBMIT`, `INCLUDE`,
`CALL TRANSACTION`, `INHERITING FROM`, `INTERFACES`, `TYPE REF TO`, `CREATE OBJECT`, `NEW`,
정적 호출(`=>`), 인터페이스 호출(`~`), `SELECT`/`JOIN`/`INSERT`/`UPDATE`/`MODIFY`/`DELETE`,
`TABLES`, `TYPE`/`LIKE`, `MESSAGE`, `AUTHORITY-CHECK`, `GET BADI`, 스마트폼 `FORMNAME`,
`ENHANCEMENT-POINT`.

## 사용법

저장소의 `code/` 디렉토리에서 실행합니다 (`--explain` 사용 시 NLWeb의 LLM 계층을 재사용).

```bash
# 1. 스캔 — 오브젝트 분류, 참조 집중 오브젝트(변경 시 파급이 큰 순서)
python -m tools.sap_impact.cli scan /path/to/sap-code --index /tmp/sap.json

# 2. 지정 오브젝트 변경의 영향
python -m tools.sap_impact.cli impact /path/to/sap-code --objects ZORDER_HDR --hops 3

# 3. 수정내역(git) 기반 — abapGit 미러의 커밋 범위로 변경 오브젝트를 자동 식별
python -m tools.sap_impact.cli changes /path/to/sap-code --rev main..feature --history 5

# 4. 자연어 프롬프트 — 업무 용어로 대상을 찾아 영향 분석
python -m tools.sap_impact.cli ask /path/to/sap-code "구매요청 승인 로직 고치면 뭐가 영향받아?"

# 5. 사용처 조회 (SE84 where-used 대응)
python -m tools.sap_impact.cli where-used /path/to/sap-code --object ZCL_ORDER_SERVICE

# 6. 장애 역추적 — 증상에서 최근 변경으로 거꾸로. 원인 후보를 커밋·작성자·경로와 함께 순위로
python -m tools.sap_impact.cli incident /path/to/sap-code "ZORDER 화면 오류" --since "14 days ago"

# 7. 기간 요약 — 변경 건수·위험도 분포·외부 계약 도달·핫스팟 변경·고위험 커밋 (보고용)
python -m tools.sap_impact.cli summary /path/to/sap-code --since "7 days ago"

# LLM 설명 추가 (config/config_llm.yaml 의 프로바이더 사용)
python -m tools.sap_impact.cli impact /path/to/sap-code --objects ZORDER_HDR --explain
# 실제 호출 없이 프롬프트만 확인
python -m tools.sap_impact.cli impact /path/to/sap-code --objects ZORDER_HDR --explain --dry-run
```

주요 옵션: `--hops`(추적 깊이, 기본 3) `--index`(스캔 캐시 재사용) `--brief`(근거 코드 생략)
`--json`(결과 저장) `--provider` `--level`.

## 개발 리더의 4가지 질문에 대응

| 순간 | 질문 | 명령 / API |
|---|---|---|
| 전송 승인 | "이거 나가도 돼?" | `changes` / `analyzeChangeSet` |
| 장애 발생 | "어제 ZORDER 죽었는데 최근 변경 중 뭐 때문이야?" | `incident` / `traceIncident` |
| 인수인계·문의 | "이거 어디서 쓰여? 뭘 건드리면 어디까지 가?" | `where-used`, `impact` / `whereUsed`, `analyzeImpact` |
| 보고 | "이번 주 변경 관리 어땠어?" | `summary` / `getPeriodSummary` |

장애 역추적은 영향 분석의 역방향입니다. 증상 오브젝트가 **의존하는** 것들(정방향 closure)과
기간 내 변경 오브젝트의 교집합을 증상까지의 거리·최근성·DDIC 여부로 순위 매깁니다.
경로에 동적 호출이 있으면 "후보 밖의 변경도 원인일 수 있다"고 명시합니다 — 후보 목록은 순위이지
원인 확정이 아닙니다.

## 출력 해석

- **위험도** — `LOW/MEDIUM/HIGH/CRITICAL`. 영향 건수, DDIC 변경 여부, 외부 계약 도달,
  RFC/COMMIT 포함, 고참조 오브젝트 여부를 규칙으로 합산합니다. 판정 근거가 항상 함께 출력되므로
  고객이 규칙 자체를 놓고 논의할 수 있습니다.
- **영향 오브젝트** — 홉 수, 참조 경로, 그 엣지를 만든 실제 코드 라인.
- **외부 계약 도달** — 펑션모듈(RFC), 트랜잭션, IDoc, OData 서비스 등 연계 시스템·사용자에게
  노출되는 지점. 여기 닿으면 릴리스 리스크입니다.
- **회귀 테스트 후보** — 사람이 실행할 수 있는 단위(트랜잭션/리포트/서비스/화면)로 환산.
- **정적 분석 사각지대** — `CALL FUNCTION lv_name`, `SELECT ... FROM (lv_tab)`, RTTI 등
  **정적으로 알 수 없는 호출**. 그래프가 불완전한 지점을 숨기지 않고 명시합니다.

## 한계

- 정적 분석이므로 동적 호출은 원리상 잡히지 않습니다(위 사각지대로 보고).
- 커스터마이징 테이블 기반 분기, BAdI 필터, 확장 스팟 구현은 코드만으로 판정 불가합니다.
- 표준 SAP 오브젝트(`CL_*`, `MARA`, `BAPI_*`)는 그래프 노드가 아니라 '미해결 참조'로 집계됩니다.
- 시스템 내부의 SE84 where-used와 달리 **디렉토리에 있는 코드만** 봅니다. 디렉토리가 전체
  커스텀 코드를 담고 있는지는 별도 확인이 필요합니다.

## 테스트

```bash
python -m tools.sap_impact.test_sap_impact
```

`samples/` 에는 ABAP(테이블·데이터엘리먼트·클래스·인터페이스·펑션그룹·리포트·CDS·트랜잭션)과
BTP(CAP 스키마·서비스·핸들러, UI5 manifest·뷰·컨트롤러·프래그먼트)가 실제 참조 관계를 갖도록
구성돼 있어, 스캔 한 번으로 전 구간 동작을 확인할 수 있습니다.

## M365 / Microsoft Foundry 배포

`service/` 에 HTTP 서비스 계층이 있습니다. 분석 엔진을 Foundry Agent Service의 **OpenAPI 도구**로
노출하고, 그 에이전트를 **Microsoft 365 Copilot / Teams**에 게시하는 경로입니다.
설정·배포·인증·게시 절차는 [service/README.md](service/README.md) 를 참조하십시오.

이 배포에서는 해석 계층이 서비스에서 에이전트로 이동합니다. 서비스는 사실(참조 경로·근거·위험도)만
반환하고, 에이전트 지시문이 "도구 응답에 없는 오브젝트명을 만들지 말 것"을 강제합니다.

| CLI | Foundry 배포 |
|---|---|
| 디렉토리 스캔 | abapGit 미러 git clone/pull → 백그라운드 인덱싱, 디스크 캐시 |
| `index.json` | 컨테이너 메모리 + 영구 볼륨 캐시 (규모 확대 시 Azure AI Search + 그래프 저장소) |
| `explain.py` 의 LLM 호출 | Foundry 에이전트의 모델 (`service/agent_instructions.md`) |
| CLI 명령 | OpenAPI 도구 operation (`analyzeImpact`, `analyzeChangeSet`, `whereUsed` 등) |
| 터미널 | Microsoft 365 Copilot / Teams 대화
