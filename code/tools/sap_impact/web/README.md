# 웹 앱 (React)

SAP 변경 영향 분석의 사용자 화면입니다. Vite + React + TypeScript, 외부 UI 라이브러리 없이
자체 토큰 기반 스타일을 씁니다(사내망·Teams 테마 대응).

## 화면

| 경로 | 화면 | 개발자가 여기서 답을 얻는 질문 |
|---|---|---|
| `/app/` | 대시보드 | 이 분석을 지금 믿어도 되나(인덱스 시각·미해결 참조·사각지대), 어디가 위험한가(참조 집중), 최근 뭐가 바뀌었나 |
| `/app/impact` | 영향 분석 | 이걸 고치면 어디까지 가나 — 홉별 경로 그래프, 근거 코드, 회귀 테스트 범위, 사각지대 |
| `/app/review` | 코드 리뷰 | 이 변경이 뭘 깨뜨리나 — diff 라인별 위험 주석 + 그 오브젝트를 참조하는 곳 |
| `/app/explore` | 오브젝트 탐색 | 이건 어디서 쓰나(SE84 where-used), 업무 용어로 오브젝트 찾기 |
| `/app/config` | 탭 설정 | Teams 채널 탭 추가 시 기본 코드베이스 선택 |

에이전트 패널은 모든 화면에서 열립니다. 브라우저가 Foundry 자격 증명을 갖지 않도록
서비스(`/agent/chat`)를 거쳐 호출하며, 현재 화면 컨텍스트(코드베이스·경로)를 함께 보냅니다.

## 설계 원칙

- **근거 없는 주장 금지** — 영향 항목은 항상 `파일:라인`과 원본 구문을 달고 나옵니다.
- **사각지대를 숨기지 않음** — 동적 호출은 그래프에 안 잡힌다는 사실을 화면에 남깁니다.
- **신선도 먼저** — 개발자가 처음 확인하는 것은 "이 인덱스가 언제 것인가"입니다.
- **그래프는 홉 축으로** — 전체 관계도(hairball)가 아니라 변경에서 몇 홉인지로 배치합니다.

## 개발

```bash
# 1) API 서버 (다른 터미널, code/ 에서)
SAP_IMPACT_PATH=tools/sap_impact/samples \
  python -m uvicorn tools.sap_impact.service.app:app --port 8099

# 2) 웹 앱 (이 디렉토리에서)
npm install
npm run dev          # http://localhost:5173/app/ — API 는 8099 로 프록시
npm run typecheck
npm run build        # -> ../service/webdist (서비스가 /app 에서 서빙)
```

운영 배포는 `service/Dockerfile` 이 이 빌드를 포함합니다. 별도 프런트엔드 호스팅이 필요 없습니다.
