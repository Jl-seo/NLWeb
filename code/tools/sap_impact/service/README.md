# M365 + Microsoft Foundry 배포

CLI를 그대로 M365에 올릴 수는 없습니다. 이 디렉토리는 분석 엔진을 **Foundry Agent Service의
OpenAPI 도구**로 노출하고, 그 에이전트를 **Microsoft 365 Copilot / Teams**에 게시하기 위한
서비스 계층입니다.

```
SAP 코드 (abapGit 미러 / BTP 프로젝트)
   │  git clone·pull 후 스캔, 인덱스는 디스크 캐시
   ▼
[이 서비스]  Container Apps 또는 App Service          ← 참조 그래프 + 규칙 기반 위험도. LLM 없음
   │  OpenAPI 3.0 (operationId, x-api-key 또는 관리 ID)
   ▼
[Foundry 에이전트]  Microsoft Foundry Agent Service    ← 모델이 근거를 읽고 한국어로 설명
   │  Publish → Azure Bot Service 자동 생성
   ▼
[Microsoft 365 Copilot / Teams]                        ← 개발자·현업이 대화로 질문
```

## 왜 서비스는 LLM을 호출하지 않는가

CLI에서는 `explain.py` 가 직접 LLM을 호출했지만, Foundry 배포에서는 **해석 계층이 에이전트로
이동**합니다. 서비스는 사실(참조 경로·파일·라인·원본 구문·규칙 기반 위험도)만 반환하고,
에이전트 지시문(`agent_instructions.md`)이 "도구 응답에 없는 오브젝트명을 만들지 말 것"을
강제합니다. 모델을 사실 계층 밖에 두는 것이 분석을 재현 가능하게 만드는 유일한 방법입니다.

## 1. 서비스 배포

환경변수:

| 변수 | 용도 |
|---|---|
| `SAP_IMPACT_GIT_URL` / `SAP_IMPACT_GIT_BRANCH` | abapGit 미러 저장소 (Azure Repos, GitHub) |
| `SAP_IMPACT_PATH` | 또는, 컨테이너에 마운트된 코드 디렉토리 (Azure Files 등) |
| `SAP_IMPACT_WORKSPACES` | 여러 코드베이스를 쓸 때 JSON 배열 또는 파일 경로 |
| `SAP_IMPACT_API_KEY` | `x-api-key` 검증값. 미설정 시 인증 없음(사설망/Easy Auth 전제) |
| `SAP_IMPACT_PUBLIC_URL` | 스키마의 server URL. Foundry가 호출할 공개 주소 |
| `SAP_IMPACT_CACHE` | 인덱스 캐시 경로 (영구 볼륨 권장) |

추가로 에이전트 패널을 쓰려면 `FOUNDRY_PROJECT_ENDPOINT`(및 선택적으로 `FOUNDRY_AGENT_NAME`)를
지정하고, 컨테이너의 관리 ID에 Foundry 프로젝트 권한을 부여합니다.

```bash
# Container Apps 예시 (Dockerfile 이 React 앱까지 함께 빌드)
az containerapp up -n sap-impact -g <rg> --source code/tools/sap_impact \
  --env-vars SAP_IMPACT_GIT_URL=https://dev.azure.com/<org>/<proj>/_git/<repo> \
             SAP_IMPACT_API_KEY=<key> SAP_IMPACT_PUBLIC_URL=https://<fqdn> \
             FOUNDRY_PROJECT_ENDPOINT=https://<res>.services.ai.azure.com/api/projects/<proj>
```

기동 시 캐시된 인덱스를 읽고, 없으면 백그라운드로 스캔합니다. 스캔 중 요청은 503과 함께
"인덱싱 진행 중" 을 반환하며, 에이전트 지시문이 이 경우 재시도를 안내하도록 되어 있습니다.
전송 후 최신화는 `POST /workspaces/{id}/reindex` 를 CI 파이프라인에서 호출하면 됩니다.

## 2. OpenAPI 스키마 생성

```bash
cd code
python -m tools.sap_impact.service.export_openapi \
    --url https://<서비스 FQDN> --api-key-header --out openapi.json
```

FastAPI는 3.1을 생성하므로 이 스크립트가 3.0.3으로 변환하고, Foundry 요구사항(모든 operation에
`operationId`, server URL 포함)을 검증합니다.

## 3. Foundry 에이전트 등록

포털: Foundry 포털 → 프로젝트 → 에이전트 생성 → **Tools → Add → Custom → OpenAPI tool** →
스키마 붙여넣기 → 지시문에 `agent_instructions.md` 내용 입력.

코드(환경별 재현용):

```bash
python -m tools.sap_impact.service.foundry_agent \
    --project-endpoint https://<resource>.services.ai.azure.com/api/projects/<project> \
    --model gpt-5-mini --openapi openapi.json \
    --auth connection --connection-id <custom-keys 연결 ID>
```

인증 선택 (권장 순):

1. **managed** — Foundry 관리 ID가 Entra 토큰으로 API 호출. 유출될 비밀이 없어 운영에 적합.
   App Service 앞단은 [Easy Auth 구성 문서](https://learn.microsoft.com/azure/app-service/configure-authentication-ai-foundry-openapi-tool) 참조.
2. **connection** — API 키를 Foundry `custom keys` 연결에 저장하고 `x-api-key` 로 전송.
   키를 재발급하면 연결도 갱신해야 합니다.
3. **anonymous** — 사설망 내부에서만. 공개 엔드포인트에는 쓰지 마십시오.

## 4. Microsoft 365 Copilot / Teams 게시

Foundry 포털에서 **Publish → Teams and Microsoft 365 Copilot**.

- Azure Bot Service 리소스가 자동 생성되어 M365 채널과 에이전트 사이를 중계합니다.
- 사전 요구: `Microsoft.BotService` 공급자 등록, 게시 리소스 그룹에 **Azure Bot Service
  Contributor**, 프로젝트에 **Foundry User** 역할.
- 공개 범위: **Just you**(승인 불필요) 또는 **People in your organization**
  (M365 관리센터 승인 후 "Built by your org" 에 노출).
- 공용 네트워크를 막은 프로젝트는 포털 게시가 지원되지 않으므로 REST API 경로를 사용합니다.

**거버넌스 주의**: M365/Teams에 게시하면 에이전트 이름·설명과 **사용자 질의에 대한 응답 데이터**가
M365 서비스에서 처리·저장됩니다. SAP 소스 코드 조각이 응답 근거로 포함되므로, 고객의 데이터
분류·리전 정책에 맞는지 게시 전에 확인해야 합니다. 필요하면 응답 근거의 코드 구문 노출 범위를
줄이도록 `SAP_IMPACT_MAX_IMPACTED` 와 지시문을 조정하십시오.

## 웹 앱과 Teams 패키징

사용자 화면은 React 앱입니다([`../web/`](../web/README.md)) — 대시보드, 영향 분석, 코드 리뷰,
오브젝트 탐색, 그리고 모든 화면에서 열리는 에이전트 패널. 서비스가 `/app` 에서 이 앱을 서빙하므로
프런트엔드를 따로 호스팅하지 않습니다.

Teams는 이 앱을 꽂는 껍데기입니다: 매니페스트의 탭이 `https://<host>/app/` 을 가리키고,
채팅용 요약은 Adaptive Card(`POST /cards/impact`)로 나갑니다. 패키징은
[`../teams_app/`](../teams_app/README.md) 참조.

```bash
python tools/sap_impact/teams_app/build_package.py \
    --host <서비스 FQDN> --app-id <새 GUID> --developer "회사명"
```

탭은 브라우저이므로 API 키를 가질 수 없습니다. 서비스는 `x-api-key`(Foundry) 외에
App Service 인증(Easy Auth)이 주입하는 `X-MS-CLIENT-PRINCIPAL-ID` 를 유효한 자격 증명으로
인정합니다. **Easy Auth 같은 게이트웨이 없이 공개 노출하면 이 헤더를 위조할 수 있으므로**
탭을 사용할 때는 반드시 앞단에 인증을 두십시오.

## 엔드포인트

| operationId | 메서드 | 용도 |
|---|---|---|
| `analyzeImpact` | POST `/impact` | 지정 오브젝트 변경의 영향 범위 |
| `analyzeImpactByPrompt` | POST `/ask` | 업무 용어로 대상을 찾아 영향 분석 |
| `analyzeChangeSet` | POST `/changes` | git 수정내역(전송 대상 커밋 범위)의 영향 |
| `whereUsed` | GET `/where-used` | 단일 오브젝트 사용처 (SE84 대응) |
| `searchObjects` | GET `/objects` | 오브젝트 검색 |
| `listWorkspaces` | GET `/workspaces` | 코드베이스·인덱싱 상태 |
| `reindexWorkspace` | POST `/workspaces/{id}/reindex` | 재인덱싱 (CI에서 호출) |
| `healthCheck` | GET `/health` | 상태 확인 |
| `renderImpactCard` | POST `/cards/impact` | 결과를 Adaptive Card로 렌더링 (봇·메시지 확장·Copilot 플러그인 템플릿) |

| `traceIncident` | POST `/incident` | 장애 증상 → 최근 변경 역추적, 원인 후보 순위 |
| `getPeriodSummary` | GET `/summary` | 기간 내 변경 관리 요약 (보고용) |
| `getDashboard` | GET `/dashboard` | 코드베이스 건강도·핫스팟·최근 변경 |
| `buildCodeReview` | POST `/review` | 변경 diff + 라인별 위험 주석 + 오브젝트별 참조자 |
| `chatWithAgent` | POST `/agent/chat` | Foundry 에이전트 대화 (SSE 스트리밍) |
| `getAgentStatus` | GET `/agent/status` | 에이전트 설정 여부 |

웹 앱은 `/app` 에서 서빙되며 딥링크는 SPA fallback 으로 처리됩니다.

모든 영향 응답 항목은 `evidence`(파일·라인·원본 구문)를 포함합니다. 에이전트는 이 값을 인용해야
하며, 근거 없이 오브젝트명을 언급하지 않도록 지시문에 명시돼 있습니다.

## 로컬 실행 / 테스트

```bash
cd code
pip install -r tools/sap_impact/service/requirements.txt
(cd tools/sap_impact/web && npm install && npm run build)   # 웹 앱 빌드 (최초 1회)
SAP_IMPACT_PATH=tools/sap_impact/samples \
  uvicorn tools.sap_impact.service.app:app --port 8080     # 앱 /app · API 문서 /docs

SAP_IMPACT_PATH=tools/sap_impact/samples \
  python -m tools.sap_impact.service.test_service
```

## 운영 시 확인 필요

- **인덱싱 시간** — 샘플은 즉시지만 수만 오브젝트 규모는 분 단위입니다. 실제 고객 코드로 측정해야
  재인덱싱 주기와 컨테이너 사양을 정할 수 있습니다.
- **동시성** — 인덱스는 메모리 상주이므로 코드베이스 크기에 비례해 메모리가 필요합니다.
- **권한** — 현재 서비스는 호출자를 구분하지 않습니다. 모듈·패키지별 접근 제어가 필요하면
  Easy Auth로 받은 사용자 신원을 기준으로 응답을 필터링하는 계층을 추가해야 합니다.
