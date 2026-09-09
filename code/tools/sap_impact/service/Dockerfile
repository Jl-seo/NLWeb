# SAP 변경 영향 분석 서비스 — Azure Container Apps / App Service(컨테이너) 배포용
FROM python:3.11-slim

# git: abapGit 미러 clone/pull 및 수정내역(diff) 분석에 사용
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY service/requirements.txt /app/service-requirements.txt
RUN pip install --no-cache-dir -r /app/service-requirements.txt

# sap_impact 패키지 전체를 복사 (service 는 상위 패키지의 분석 모듈을 사용)
COPY . /app/sap_impact/
RUN rm -rf /app/sap_impact/samples

ENV SAP_IMPACT_CACHE=/home/cache \
    PYTHONUNBUFFERED=1 \
    PORT=8080
RUN mkdir -p /home/cache

EXPOSE 8080
CMD ["sh", "-c", "uvicorn sap_impact.service.app:app --host 0.0.0.0 --port ${PORT}"]
