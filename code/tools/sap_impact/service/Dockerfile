# SAP 변경 영향 분석 — 웹 앱 + API 단일 컨테이너
# 빌드 컨텍스트는 sap_impact 디렉토리:
#   docker build -f service/Dockerfile -t sap-impact code/tools/sap_impact

# 1단계: React 앱 빌드 (결과물은 service/webdist)
FROM node:22-slim AS web
WORKDIR /src
COPY web/package.json web/package-lock.json /src/web/
RUN cd web && npm ci
COPY web /src/web
RUN cd web && npm run build

# 2단계: 분석 엔진 + API + 정적 앱 서빙
FROM python:3.11-slim

# git: abapGit 미러 clone/pull 및 수정내역(diff) 분석에 사용
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY service/requirements.txt /app/service-requirements.txt
RUN pip install --no-cache-dir -r /app/service-requirements.txt

COPY . /app/sap_impact/
RUN rm -rf /app/sap_impact/samples /app/sap_impact/web
COPY --from=web /src/service/webdist /app/sap_impact/service/webdist

ENV SAP_IMPACT_CACHE=/home/cache \
    PYTHONUNBUFFERED=1 \
    PORT=8080
RUN mkdir -p /home/cache

EXPOSE 8080
CMD ["sh", "-c", "uvicorn sap_impact.service.app:app --host 0.0.0.0 --port ${PORT}"]
