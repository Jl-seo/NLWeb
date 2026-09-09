"""
HTTP service that exposes the SAP impact analysis as an OpenAPI tool for
Microsoft Foundry Agent Service.

Division of labour in the Azure deployment differs from the CLI on purpose:

    CLI        : graph -> rules -> local LLM call (explain.py)
    Foundry    : graph -> rules -> *the Foundry agent's model* narrates

So this service never calls an LLM. It returns facts with citations
(file, line, source statement) and the agent, whose instructions forbid
inventing object names, turns them into the answer the user reads in Teams or
Microsoft 365 Copilot. Keeping the model outside the fact layer is what makes
the analysis reproducible.

Every operation carries an explicit operationId: the Foundry OpenAPI tool
requires one, and it is what the model sees when choosing a tool.
"""

import os
import sys
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "sap_impact.service"

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import model as M
from .. import search as search_mod
from .. import vcs
from ..impact import analyze
from .cards import impact_card
from .workspace import WorkspaceRegistry, load_configs

API_KEY = os.environ.get("SAP_IMPACT_API_KEY", "")
PUBLIC_BASE_URL = os.environ.get("SAP_IMPACT_PUBLIC_URL", "http://localhost:8080")
MAX_IMPACTED = int(os.environ.get("SAP_IMPACT_MAX_IMPACTED", "60"))
TEAMS_APP_ID = os.environ.get("SAP_IMPACT_TEAMS_APP_ID", "")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

registry = WorkspaceRegistry(load_configs())

app = FastAPI(
    title="SAP 변경 영향 분석 API",
    version="1.0.0",
    description=(
        "SAP(ABAP/BTP) 코드베이스의 참조 그래프를 기반으로 변경 영향 범위를 계산합니다. "
        "모든 응답은 파일·라인·원본 구문 근거를 포함하며, 해석이나 추정은 포함하지 않습니다."
    ),
    servers=[{"url": PUBLIC_BASE_URL}],
)


# ------------------------------------------------------------------- security


def require_key(
    x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
    x_ms_client_principal_id: Optional[str] = Header(
        default=None, alias="X-MS-CLIENT-PRINCIPAL-ID"),
) -> None:
    """
    Two callers, two credentials.

    Foundry sends the API key from its 'custom keys' connection. The Teams tab is
    a browser and must never hold that key, so it is authenticated upstream by
    App Service authentication (Easy Auth), which strips client-supplied
    X-MS-CLIENT-PRINCIPAL-* headers and injects its own after validating the
    Entra token. Trusting that header is therefore safe *only* behind Easy Auth
    or an equivalent gateway -- see service/README.md before exposing the app
    directly.

    With no key configured the service runs open, which is appropriate only on a
    private network or during local development.
    """
    if not API_KEY:
        return
    if x_api_key == API_KEY:
        return
    if x_ms_client_principal_id:
        return
    raise HTTPException(status_code=401, detail="invalid or missing credentials")


# --------------------------------------------------------------------- models


class Evidence(BaseModel):
    file: str = Field(default="", description="근거 파일 경로")
    line: int = Field(default=0, description="근거 라인 번호")
    statement: str = Field(default="", description="참조를 만든 실제 소스 구문")
    reference_kind: str = Field(default="", description="참조 종류 (SELECT, CALL_FUNCTION 등)")


class ImpactedObject(BaseModel):
    object_key: str = Field(description="영향받는 오브젝트 키 (예: PROG/ZMM_PR_APPROVE)")
    object_type: str = Field(description="오브젝트 타입 코드")
    object_type_label: str = Field(description="오브젝트 타입 한글 명칭")
    description: str = Field(default="", description="오브젝트 설명(DDIC 텍스트 등)")
    hops: int = Field(description="변경 오브젝트로부터의 참조 거리")
    path: List[str] = Field(description="변경 오브젝트에서 여기까지의 최단 참조 경로")
    evidence: Evidence


class BlindSpot(BaseModel):
    object_key: str
    file: str = ""
    line: int = 0
    reason: str = Field(description="정적 분석으로 해결 불가능한 이유")


class ImpactResponse(BaseModel):
    workspace: str
    changed_objects: List[str] = Field(description="분석 대상 변경 오브젝트")
    not_found: List[str] = Field(default_factory=list, description="코드베이스에 없는 지정 오브젝트")
    severity: str = Field(description="규칙 기반 위험도: LOW / MEDIUM / HIGH / CRITICAL")
    severity_reasons: List[str] = Field(description="위험도 판정 근거")
    impacted_count: int
    impacted: List[ImpactedObject]
    truncated: bool = Field(default=False, description="impacted 목록이 잘렸는지 여부")
    external_contracts: List[str] = Field(
        default_factory=list, description="연계 시스템·사용자에게 노출되는 도달 오브젝트")
    regression_scope: List[str] = Field(
        default_factory=list, description="실행 가능한 단위로 환산한 회귀 테스트 후보")
    blind_spots: List[BlindSpot] = Field(
        default_factory=list, description="동적 호출 등 정적 분석 사각지대")
    resolved_from_prompt: List[Dict[str, Any]] = Field(
        default_factory=list, description="프롬프트로 대상을 찾은 경우 그 근거")
    changed_files: List[Dict[str, str]] = Field(
        default_factory=list, description="git 기반 분석인 경우 변경 파일 목록")


class ImpactRequest(BaseModel):
    objects: List[str] = Field(description="변경된 오브젝트명 또는 키 (예: ZORDER_HDR, CLAS/ZCL_ORDER)")
    workspace: Optional[str] = Field(default=None, description="workspace id. 하나뿐이면 생략 가능")
    hops: int = Field(default=3, ge=1, le=6, description="참조 추적 최대 깊이")


class PromptRequest(BaseModel):
    prompt: str = Field(description="업무 용어 질문 (예: 구매요청 승인 로직 고치면 뭐가 영향받아?)")
    workspace: Optional[str] = None
    hops: int = Field(default=3, ge=1, le=6)
    select: int = Field(default=2, ge=1, le=5, description="상위 후보 중 분석 대상으로 삼을 개수")


class ChangeSetRequest(BaseModel):
    workspace: Optional[str] = None
    revision_range: Optional[str] = Field(
        default=None, description="git 리비전 범위 (예: HEAD~1, main..feature). 생략 시 작업 트리")
    hops: int = Field(default=3, ge=1, le=6)


class ObjectSummary(BaseModel):
    object_key: str
    object_type: str
    object_type_label: str
    name: str
    description: str = ""
    files: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    direct_dependents: int = Field(description="이 오브젝트를 직접 참조하는 오브젝트 수")


class WhereUsedResponse(BaseModel):
    workspace: str
    object: ObjectSummary
    used_by: List[ImpactedObject]
    uses: List[str] = Field(description="이 오브젝트가 참조하는 대상")


class WorkspaceInfo(BaseModel):
    id: str
    kind: str
    description: str = ""
    ready: bool
    indexing: bool
    indexed_at: str = ""
    last_error: str = ""
    objects: int = 0
    references: int = 0
    unresolved: int = 0
    blind_spot_objects: int = 0


# ------------------------------------------------------------------ endpoints


@app.get("/health", operation_id="healthCheck", summary="서비스 상태 확인", tags=["system"])
def health() -> Dict[str, Any]:
    return {"status": "ok", "workspaces": registry.ids()}


@app.get("/workspaces", operation_id="listWorkspaces", response_model=List[WorkspaceInfo],
         summary="등록된 SAP 코드베이스 목록과 인덱싱 상태", tags=["system"],
         dependencies=[Depends(require_key)])
def list_workspaces() -> List[WorkspaceInfo]:
    return [WorkspaceInfo(**item) for item in registry.describe()]


@app.post("/workspaces/{workspace_id}/reindex", operation_id="reindexWorkspace",
          summary="코드베이스 재인덱싱 (git pull 후 재스캔)", tags=["system"],
          dependencies=[Depends(require_key)])
def reindex(workspace_id: str) -> Dict[str, str]:
    try:
        registry.reindex(workspace_id, background=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "reindexing", "workspace": workspace_id}


@app.get("/objects", operation_id="searchObjects", response_model=List[ObjectSummary],
         summary="오브젝트 검색 (이름·설명·업무 용어)", tags=["analysis"],
         dependencies=[Depends(require_key)])
def search_objects(
    q: str = Query(description="검색어. 오브젝트명 일부 또는 업무 용어"),
    workspace: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> List[ObjectSummary]:
    state = _ready(workspace)
    candidates = search_mod.resolve(state.codebase, q, limit=limit)
    return [_object_summary(state, c.key) for c in candidates]


@app.get("/where-used", operation_id="whereUsed", response_model=WhereUsedResponse,
         summary="단일 오브젝트의 사용처 (SE84 where-used 대응)", tags=["analysis"],
         dependencies=[Depends(require_key)])
def where_used(
    object: str = Query(description="오브젝트명 또는 키"),
    workspace: Optional[str] = Query(default=None),
) -> WhereUsedResponse:
    state = _ready(workspace)
    key = _resolve_one(state, object)
    edges = state.graph.dependents.get(key, [])
    used_by = [
        ImpactedObject(
            object_key=edge.source,
            object_type=_type_of(state, edge.source),
            object_type_label=M.type_label(_type_of(state, edge.source)),
            description=_desc_of(state, edge.source),
            hops=1,
            path=[key, edge.source],
            evidence=_evidence(state, edge),
        )
        for edge in sorted(edges, key=lambda e: (e.source, e.line))
    ]
    uses = sorted({edge.target for edge in state.graph.dependencies.get(key, [])})
    return WhereUsedResponse(workspace=state.config.id, object=_object_summary(state, key),
                             used_by=used_by, uses=uses)


@app.post("/impact", operation_id="analyzeImpact", response_model=ImpactResponse,
          summary="지정한 오브젝트를 변경할 때의 영향 범위", tags=["analysis"],
          dependencies=[Depends(require_key)])
def analyze_impact(request: ImpactRequest) -> ImpactResponse:
    state = _ready(request.workspace)
    keys = [_resolve_one(state, token, strict=False) for token in request.objects]
    report = analyze(state.codebase, state.graph, keys, max_hops=request.hops)
    return _to_response(state, report)


@app.post("/ask", operation_id="analyzeImpactByPrompt", response_model=ImpactResponse,
          summary="업무 용어 질문으로 대상 오브젝트를 찾아 영향 분석", tags=["analysis"],
          dependencies=[Depends(require_key)])
def analyze_by_prompt(request: PromptRequest) -> ImpactResponse:
    state = _ready(request.workspace)
    candidates = search_mod.resolve(state.codebase, request.prompt, limit=max(request.select, 5))
    if not candidates:
        raise HTTPException(status_code=404,
                            detail=f"'{request.prompt}' 에 해당하는 오브젝트를 찾지 못했습니다.")
    selected = [c.key for c in candidates[: request.select]]
    selected = _expand_transactions(state, selected)
    report = analyze(state.codebase, state.graph, selected, max_hops=request.hops)
    response = _to_response(state, report)
    response.resolved_from_prompt = [
        {"object_key": c.key, "score": round(c.score, 1), "matched_because": "; ".join(c.why)}
        for c in candidates
    ]
    return response


@app.post("/changes", operation_id="analyzeChangeSet", response_model=ImpactResponse,
          summary="git 수정내역(전송 대상 커밋 범위)의 영향 분석", tags=["analysis"],
          dependencies=[Depends(require_key)])
def analyze_changes(request: ChangeSetRequest) -> ImpactResponse:
    state = _ready(request.workspace)
    try:
        changes = vcs.changed_files(state.codebase.root, rev_range=request.revision_range)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    keys, unmapped = vcs.map_files_to_objects(state.codebase, changes)
    if not keys:
        raise HTTPException(status_code=404,
                            detail="변경 파일이 SAP 개발 오브젝트로 매핑되지 않았습니다.")
    report = analyze(state.codebase, state.graph, keys, max_hops=request.hops)
    response = _to_response(state, report)
    response.changed_files = [
        {"status": vcs.STATUS_LABEL.get(c.status, c.status), "path": c.path} for c in changes
    ]
    if unmapped:
        response.severity_reasons.append(
            f"오브젝트로 매핑되지 않은 변경 파일 {len(unmapped)}건 (분석 범위에서 제외)")
    return response


class CardRequest(BaseModel):
    objects: List[str] = Field(default_factory=list, description="변경 오브젝트 (impact 모드)")
    prompt: Optional[str] = Field(default=None, description="업무 용어 질문 (ask 모드)")
    revision_range: Optional[str] = Field(default=None, description="git 범위 (changes 모드)")
    workspace: Optional[str] = None
    hops: int = Field(default=3, ge=1, le=6)


@app.post("/cards/impact", operation_id="renderImpactCard",
          summary="영향 분석 결과를 Adaptive Card로 렌더링", tags=["ui"],
          dependencies=[Depends(require_key)])
def render_card(request: CardRequest) -> Dict[str, Any]:
    """
    Same analysis, chat-shaped: a summary card with the decision-grade facts and
    a deep link into the tab for the full table. Bots and message extensions post
    this; a Copilot API plugin can use it as a dynamic response template.
    """
    if request.prompt:
        report = analyze_by_prompt(PromptRequest(prompt=request.prompt, workspace=request.workspace,
                                                 hops=request.hops, select=2))
    elif request.revision_range is not None and not request.objects:
        report = analyze_changes(ChangeSetRequest(workspace=request.workspace,
                                                  revision_range=request.revision_range,
                                                  hops=request.hops))
    elif request.objects:
        report = analyze_impact(ImpactRequest(objects=request.objects, workspace=request.workspace,
                                              hops=request.hops))
    else:
        raise HTTPException(status_code=400,
                            detail="objects, prompt, revision_range 중 하나는 지정해야 합니다.")

    payload = report.model_dump()
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": impact_card(payload, tab_url=f"{PUBLIC_BASE_URL}/ui/tab.html",
                               app_id=TEAMS_APP_ID),
    }


@app.get("/tab", include_in_schema=False)
def tab_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/tab.html")


if os.path.isdir(STATIC_DIR):
    # Served from /ui so the page's relative fetches ("../impact") land on the API.
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


# ------------------------------------------------------------------- helpers


def _ready(workspace: Optional[str]):
    try:
        return registry.require_ready(workspace)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _resolve_one(state, token: str, strict: bool = True) -> str:
    cb = state.codebase
    token = token.strip()
    if token in cb.objects:
        return token
    matches = [key for key, obj in cb.objects.items() if obj.name.upper() == token.upper()]
    if matches:
        return matches[0]
    if strict:
        raise HTTPException(status_code=404, detail=f"오브젝트를 찾을 수 없습니다: {token}")
    return token  # analyzer reports it under not_found


def _expand_transactions(state, keys: List[str]) -> List[str]:
    """A transaction code holds no logic; pull in the program behind it."""
    expanded = list(keys)
    for key in keys:
        obj = state.codebase.objects.get(key)
        if not obj or obj.obj_type != M.TRANSACTION:
            continue
        for edge in state.graph.dependencies.get(key, []):
            if edge.kind == "TRANSACTION_PROGRAM" and edge.target not in expanded:
                expanded.append(edge.target)
    return expanded


def _type_of(state, key: str) -> str:
    obj = state.codebase.objects.get(key)
    return obj.obj_type if obj else M.UNKNOWN


def _desc_of(state, key: str) -> str:
    obj = state.codebase.objects.get(key)
    return (obj.description or "") if obj else ""


def _evidence(state, edge) -> Evidence:
    source = state.codebase.objects.get(edge.source)
    return Evidence(
        file=source.paths[0] if source and source.paths else "",
        line=edge.line,
        statement=edge.snippet,
        reference_kind=edge.kind,
    )


def _object_summary(state, key: str) -> ObjectSummary:
    obj = state.codebase.objects[key]
    return ObjectSummary(
        object_key=key,
        object_type=obj.obj_type,
        object_type_label=M.type_label(obj.obj_type),
        name=obj.name,
        description=obj.description or "",
        files=obj.paths[:5],
        tags=sorted(obj.tags),
        direct_dependents=state.graph.fan_in(key),
    )


def _to_response(state, report) -> ImpactResponse:
    impacted = report.impacted[:MAX_IMPACTED]
    return ImpactResponse(
        workspace=state.config.id,
        changed_objects=report.changed,
        not_found=report.missing,
        severity=report.severity,
        severity_reasons=list(report.reasons),
        impacted_count=len(report.impacted),
        truncated=len(report.impacted) > MAX_IMPACTED,
        impacted=[
            ImpactedObject(
                object_key=hit.key,
                object_type=_type_of(state, hit.key),
                object_type_label=M.type_label(_type_of(state, hit.key)),
                description=_desc_of(state, hit.key),
                hops=hit.hops,
                path=list(hit.via),
                evidence=_evidence(state, hit.edge) if hit.edge else Evidence(),
            )
            for hit in impacted
        ],
        external_contracts=report.external_contracts,
        regression_scope=report.test_scope,
        blind_spots=[
            BlindSpot(object_key=spot["object"], file=spot.get("file", ""),
                      line=spot.get("line", 0), reason=spot["reason"])
            for spot in report.blind_spots
        ],
    )


@app.on_event("startup")
def _startup() -> None:
    registry.load_cached_all()
    for workspace_id in registry.ids():
        state = registry.get(workspace_id)
        if not state.ready:
            registry.reindex(workspace_id, background=True)
