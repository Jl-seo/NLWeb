"""
LLM layer: explains an impact report that was already computed deterministically.

The prompt hands the model a closed world -- only objects that exist in the
graph -- and states plainly that it must not introduce object names of its own.
That is the difference between an impact analysis a customer can sign off on and
a plausible-sounding hallucination.

Reuses the NLWeb LLM abstraction (code/llm/llm.py), so provider choice and keys
follow the existing config_llm.yaml rather than adding a second mechanism.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

from . import model as M
from .impact import ImpactReport
from .model import CodeBase

MAX_IMPACTED_IN_PROMPT = 60
MAX_BLIND_SPOTS_IN_PROMPT = 15
MAX_DIFF_CHARS = 6000

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "severity_opinion": {"type": "string"},
        "impact_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "objects": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                    "risk": {"type": "string"},
                },
            },
        },
        "regression_tests": {"type": "array", "items": {"type": "string"}},
        "rollout_cautions": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_RULES = """\
당신은 SAP ABAP/BTP 코드베이스의 변경 영향 분석을 수행하는 시니어 SAP 아키텍트입니다.

절대 규칙:
1. 아래 '영향 오브젝트' 목록에 없는 오브젝트명을 새로 만들어내지 마십시오. 목록에 있는 것만 인용합니다.
2. 참조 경로(path)와 근거 코드(trigger)에 나타난 사실만으로 설명하십시오. 코드에 없는 업무 동작을 단정하지 마십시오.
3. 확신할 수 없는 부분은 'open_questions'에 질문으로 남기십시오. 추측을 결론처럼 쓰지 마십시오.
4. '정적 분석 사각지대'가 있으면 반드시 언급하십시오. 그래프가 불완전할 수 있다는 사실은 숨기지 않습니다.
5. 모든 출력은 한국어로 작성합니다.
"""


def build_context(cb: CodeBase, report: ImpactReport, prompt: str = "",
                  diff_text: str = "") -> str:
    lines: List[str] = []

    if prompt:
        lines.append(f"## 사용자 질문\n{prompt}\n")

    lines.append("## 변경 오브젝트")
    for key in report.changed:
        obj = cb.objects[key]
        detail = [f"- {key} ({M.type_label(obj.obj_type)})"]
        if obj.description:
            detail.append(f"설명: {obj.description}")
        if obj.tags:
            detail.append(f"특성: {', '.join(sorted(obj.tags))}")
        detail.append(f"파일: {', '.join(obj.paths[:3])}")
        lines.append("  ".join(detail))
    if report.missing:
        lines.append(f"- (코드베이스에서 못 찾은 지정 오브젝트: {', '.join(report.missing)})")

    if diff_text:
        trimmed = diff_text[:MAX_DIFF_CHARS]
        suffix = "\n... (이하 생략)" if len(diff_text) > MAX_DIFF_CHARS else ""
        lines.append(f"\n## 실제 변경 내역 (git diff)\n```diff\n{trimmed}{suffix}\n```")

    lines.append(f"\n## 규칙 기반 위험도 판정: {report.severity}")
    for reason in report.reasons:
        lines.append(f"- {reason}")

    lines.append(f"\n## 영향 오브젝트 (참조 그래프 역추적, 최대 {report.max_hops} 홉)")
    if not report.impacted:
        lines.append("- 없음 (이 코드베이스 내 참조자 없음)")
    for hit in report.impacted[:MAX_IMPACTED_IN_PROMPT]:
        obj = cb.objects.get(hit.key)
        label = M.type_label(obj.obj_type) if obj else "?"
        desc = f" | {obj.description}" if obj and obj.description else ""
        path = " -> ".join(hit.via)
        lines.append(
            f"- [{hit.hops}홉] {hit.key} ({label}){desc}\n"
            f"    경로: {path}\n"
            f"    근거: {hit.kinds[-1] if hit.kinds else ''} @ line {hit.edge.line if hit.edge else 0} — "
            f"{(hit.edge.snippet if hit.edge else '')[:150]}"
        )
    if len(report.impacted) > MAX_IMPACTED_IN_PROMPT:
        lines.append(f"- ... 외 {len(report.impacted) - MAX_IMPACTED_IN_PROMPT}건 (동일 형식)")

    if report.external_contracts:
        lines.append("\n## 외부 계약(인터페이스) 도달 오브젝트")
        for key in report.external_contracts:
            lines.append(f"- {key}")

    if report.blind_spots:
        lines.append("\n## 정적 분석 사각지대 (그래프에 안 잡히는 호출)")
        for spot in report.blind_spots[:MAX_BLIND_SPOTS_IN_PROMPT]:
            lines.append(f"- {spot['object']} @ {spot.get('file','')}:{spot['line']} — {spot['reason']}")
        if len(report.blind_spots) > MAX_BLIND_SPOTS_IN_PROMPT:
            lines.append(f"- ... 외 {len(report.blind_spots) - MAX_BLIND_SPOTS_IN_PROMPT}건")

    return "\n".join(lines)


def build_prompt(cb: CodeBase, report: ImpactReport, prompt: str = "",
                 diff_text: str = "") -> str:
    return (
        SYSTEM_RULES
        + "\n"
        + build_context(cb, report, prompt, diff_text)
        + """

## 요청
위 사실만 근거로 다음을 작성하십시오.
- summary: 이 변경이 무엇을 건드리는지 3~5문장. 업무 관점으로.
- severity_opinion: 규칙 기반 판정에 동의하는지, 다르다면 근거와 함께.
- impact_groups: 영향 오브젝트를 업무/기술 영역별로 묶고, 각 그룹이 왜 영향을 받는지와 구체적 위험.
- regression_tests: 회귀 테스트로 실행해야 할 항목. 실행 가능한 단위(트랜잭션/리포트/서비스/화면)로.
- rollout_cautions: 이행·배포 시 주의사항 (전송요청 순서, 데이터 컨버전, 다운타임, 연계 시스템 통보 등).
- open_questions: 코드만으로 판단 불가하여 담당자 확인이 필요한 사항.
"""
    )


async def explain_async(cb: CodeBase, report: ImpactReport, prompt: str = "",
                        diff_text: str = "", provider: Optional[str] = None,
                        level: str = "high", timeout: int = 120) -> Dict[str, Any]:
    """Call the configured LLM. Raises RuntimeError when the LLM layer is unusable."""
    try:
        from llm.llm import ask_llm  # NLWeb LLM abstraction (code/llm/llm.py)
    except ImportError as exc:
        raise RuntimeError(
            "LLM 계층을 불러오지 못했습니다. code/ 디렉토리에서 실행했는지, "
            f"의존성이 설치됐는지 확인하세요: {exc}"
        ) from exc

    full_prompt = build_prompt(cb, report, prompt, diff_text)
    try:
        return await ask_llm(full_prompt, RESPONSE_SCHEMA, level=level,
                             provider=provider, timeout=timeout)
    except Exception as exc:  # provider errors, missing keys, timeouts
        raise RuntimeError(f"LLM 호출 실패: {exc}") from exc


def explain(cb: CodeBase, report: ImpactReport, prompt: str = "", diff_text: str = "",
            provider: Optional[str] = None, level: str = "high") -> Dict[str, Any]:
    return asyncio.run(explain_async(cb, report, prompt, diff_text, provider, level))


def render(result: Dict[str, Any]) -> str:
    """Format the LLM answer for the terminal."""
    out: List[str] = []
    if result.get("summary"):
        out.append("■ 요약\n" + _wrap(result["summary"]))
    if result.get("severity_opinion"):
        out.append("■ 위험도 의견\n" + _wrap(result["severity_opinion"]))
    for group in result.get("impact_groups") or []:
        objects = ", ".join(group.get("objects") or [])
        out.append(
            f"■ 영향 영역: {group.get('area','')}\n"
            f"  대상: {objects}\n"
            f"  이유: {group.get('why','')}\n"
            f"  위험: {group.get('risk','')}"
        )
    for title, field in (("회귀 테스트 범위", "regression_tests"),
                         ("이행/배포 주의", "rollout_cautions"),
                         ("담당자 확인 필요", "open_questions")):
        items = result.get(field) or []
        if items:
            out.append(f"■ {title}\n" + "\n".join(f"  - {i}" for i in items))
    return "\n\n".join(out) if out else json.dumps(result, ensure_ascii=False, indent=2)


def _wrap(text: str, width: int = 96) -> str:
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append("  " + current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append("  " + current)
    return "\n".join(lines)
