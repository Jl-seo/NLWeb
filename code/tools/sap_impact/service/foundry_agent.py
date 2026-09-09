"""
Register (or update) the Foundry agent that exposes this service as an OpenAPI tool.

The portal path is equivalent and documented in README.md; this script exists so
the agent definition lives in source control and can be recreated per
environment (dev / staging / prod) instead of being clicked together by hand.

    python -m tools.sap_impact.service.foundry_agent \
        --project-endpoint https://<resource>.services.ai.azure.com/api/projects/<project> \
        --model gpt-5-mini \
        --openapi openapi.json \
        --auth connection --connection-id <custom-keys connection id>

Authentication choices, in the order you should prefer them:
  managed     - Foundry's managed identity gets an Entra token for your API's
                audience. Best for production: no secret exists to leak.
  connection  - an API key stored in a Foundry 'custom keys' connection and sent
                as x-api-key. Use when the service sits behind a simple key.
  anonymous   - no auth. Only acceptable when the service is unreachable from
                outside the private network.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict


def _load_sdk():
    """
    Import the Foundry SDK pieces. Auth detail classes have lived in both
    azure.ai.projects.models and azure.ai.agents.models across SDK versions, so
    resolve them at runtime and fail with an actionable message rather than an
    ImportError deep in the call stack.
    """
    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import OpenApiTool, PromptAgentDefinition
    except ImportError as exc:
        raise SystemExit(
            "azure-ai-projects 가 필요합니다: pip install azure-ai-projects azure-identity jsonref"
        ) from exc

    names = ("OpenApiFunctionDefinition", "OpenApiAnonymousAuthDetails",
             "OpenApiConnectionAuthDetails", "OpenApiConnectionSecurityScheme",
             "OpenApiManagedAuthDetails", "OpenApiManagedSecurityScheme")
    resolved: Dict[str, Any] = {}
    for module_name in ("azure.ai.projects.models", "azure.ai.agents.models"):
        try:
            module = __import__(module_name, fromlist=names)
        except ImportError:
            continue
        for name in names:
            if name not in resolved and hasattr(module, name):
                resolved[name] = getattr(module, name)

    return AIProjectClient, OpenApiTool, PromptAgentDefinition, resolved


def build_auth(kind: str, sdk: Dict[str, Any], connection_id: str, audience: str):
    if kind == "anonymous":
        return sdk["OpenApiAnonymousAuthDetails"]()
    if kind == "connection":
        if not connection_id:
            raise SystemExit("--auth connection 에는 --connection-id 가 필요합니다.")
        return sdk["OpenApiConnectionAuthDetails"](
            security_scheme=sdk["OpenApiConnectionSecurityScheme"](connection_id=connection_id))
    if kind == "managed":
        if not audience:
            raise SystemExit("--auth managed 에는 --audience 가 필요합니다 (대상 API의 Entra audience).")
        return sdk["OpenApiManagedAuthDetails"](
            security_scheme=sdk["OpenApiManagedSecurityScheme"](audience=audience))
    raise SystemExit(f"알 수 없는 --auth 값: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Foundry 에이전트 생성/갱신")
    parser.add_argument("--project-endpoint", default=os.environ.get("PROJECT_ENDPOINT"),
                        help="https://<resource>.services.ai.azure.com/api/projects/<project>")
    parser.add_argument("--model", default=os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5-mini"))
    parser.add_argument("--agent-name", default="sap-change-impact")
    parser.add_argument("--openapi", required=True, help="export_openapi.py 로 생성한 스키마 파일")
    parser.add_argument("--instructions", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "agent_instructions.md"))
    parser.add_argument("--auth", default="connection", choices=["anonymous", "connection", "managed"])
    parser.add_argument("--connection-id", default=os.environ.get("SAP_IMPACT_CONNECTION_ID", ""))
    parser.add_argument("--audience", default=os.environ.get("SAP_IMPACT_AUDIENCE", ""))
    parser.add_argument("--tool-name", default="sap_impact")
    args = parser.parse_args()

    if not args.project_endpoint:
        raise SystemExit("--project-endpoint 또는 PROJECT_ENDPOINT 환경변수가 필요합니다.")

    AIProjectClient, OpenApiTool, PromptAgentDefinition, sdk = _load_sdk()
    from azure.identity import DefaultAzureCredential

    with open(args.openapi, "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    with open(args.instructions, "r", encoding="utf-8") as fh:
        instructions = fh.read()

    auth = build_auth(args.auth, sdk, args.connection_id, args.audience)
    tool_description = (
        "SAP(ABAP/BTP) 코드베이스의 변경 영향 분석. 오브젝트 변경 시 영향 범위, 사용처, "
        "git 수정내역 기반 영향, 업무 용어 검색을 제공한다. 응답에는 파일·라인 근거가 포함된다."
    )

    if "OpenApiFunctionDefinition" in sdk:
        tool = OpenApiTool(openapi=sdk["OpenApiFunctionDefinition"](
            name=args.tool_name, spec=spec, description=tool_description, auth=auth))
    else:  # older SDK shape
        tool = OpenApiTool(name=args.tool_name, spec=spec,
                           description=tool_description, auth=auth)

    project = AIProjectClient(endpoint=args.project_endpoint, credential=DefaultAzureCredential())
    agent = project.agents.create_version(
        agent_name=args.agent_name,
        definition=PromptAgentDefinition(
            model=args.model,
            instructions=instructions,
            tools=[tool],
        ),
    )
    print(f"에이전트 생성/갱신 완료: name={agent.name} version={agent.version}")
    print("다음 단계: Foundry 포털에서 Publish > Teams and Microsoft 365 Copilot 으로 게시하세요.")
    print("  게시 시 Azure Bot Service 리소스가 생성되며, 조직 전체 공개는 M365 관리센터 승인이 필요합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
