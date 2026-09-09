"""
Adaptive Card rendering for the impact report.

A card is a summary, not the report: chat surfaces truncate large payloads, and
an impact set of two hundred objects does not belong in a message. The card
carries the decision-grade facts (severity, its reasons, the external contracts
reached, the blind spots) and hands off to the Teams tab for the full table.

Used by the bot/message-extension path, and usable as a dynamic response
template for a Microsoft 365 Copilot API plugin.
"""

import json
import urllib.parse
from typing import Any, Dict, List, Optional

SEVERITY_STYLE = {
    "LOW": ("Good", "낮음"),
    "MEDIUM": ("Warning", "보통"),
    "HIGH": ("Attention", "높음"),
    "CRITICAL": ("Attention", "매우 높음"),
}

TOP_N = 5


def deep_link(app_id: str, entity_id: str, sub_entity: Dict[str, Any]) -> str:
    """Teams deep link into the tab, carrying the query so the tab reopens it."""
    context = urllib.parse.quote(json.dumps({"subEntityId": json.dumps(sub_entity)}))
    return f"https://teams.microsoft.com/l/entity/{app_id}/{entity_id}?context={context}"


def impact_card(report: Dict[str, Any], tab_url: str = "", app_id: str = "",
                entity_id: str = "sapImpact") -> Dict[str, Any]:
    severity = report.get("severity", "LOW")
    color, label = SEVERITY_STYLE.get(severity, ("Default", severity))
    changed = report.get("changed_objects") or []
    impacted = report.get("impacted") or []
    total = report.get("impacted_count", len(impacted))

    body: List[Dict[str, Any]] = [
        {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {"type": "TextBlock", "text": "SAP 변경 영향 분석",
                         "weight": "Bolder", "size": "Medium", "wrap": True},
                        {"type": "TextBlock", "text": ", ".join(changed) or "(대상 없음)",
                         "isSubtle": True, "wrap": True, "spacing": "None"},
                    ],
                },
                {
                    "type": "Column",
                    "width": "auto",
                    "items": [{
                        "type": "TextBlock", "text": f"위험도 {label}",
                        "weight": "Bolder", "color": color, "wrap": False,
                    }],
                },
            ],
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "영향 오브젝트", "value": f"{total}건"},
                {"title": "외부 계약 도달", "value": _fact_list(report.get("external_contracts"))},
                {"title": "회귀 테스트 후보", "value": f"{len(report.get('regression_scope') or [])}건"},
                {"title": "정적 분석 사각지대", "value": f"{len(report.get('blind_spots') or [])}건"},
            ],
        },
    ]

    reasons = report.get("severity_reasons") or []
    if reasons:
        body.append({"type": "TextBlock", "text": "판정 근거", "weight": "Bolder",
                     "spacing": "Medium", "wrap": True})
        body.append({"type": "TextBlock", "wrap": True, "spacing": "None",
                     "text": "\n".join(f"- {r}" for r in reasons[:4])})

    if impacted:
        body.append({"type": "TextBlock", "text": f"영향 오브젝트 (상위 {min(TOP_N, len(impacted))}건)",
                     "weight": "Bolder", "spacing": "Medium", "wrap": True})
        for hit in impacted[:TOP_N]:
            evidence = hit.get("evidence") or {}
            where = f"{evidence.get('file','')}:{evidence.get('line','')}".strip(":")
            body.append({
                "type": "Container",
                "spacing": "Small",
                "items": [
                    {"type": "TextBlock", "wrap": True, "spacing": "None",
                     "text": f"**[{hit.get('hops')}홉] {hit.get('object_key')}** "
                             f"({hit.get('object_type_label','')})"},
                    {"type": "TextBlock", "wrap": True, "isSubtle": True, "spacing": "None",
                     "size": "Small", "text": f"{evidence.get('reference_kind','')} · {where}"},
                ],
            })
        if total > TOP_N:
            body.append({"type": "TextBlock", "isSubtle": True, "wrap": True, "size": "Small",
                         "text": f"... 외 {total - TOP_N}건. 전체 목록은 탭에서 확인하세요."})

    blind = report.get("blind_spots") or []
    if blind:
        body.append({
            "type": "Container",
            "style": "warning",
            "spacing": "Medium",
            "items": [
                {"type": "TextBlock", "weight": "Bolder", "wrap": True,
                 "text": f"정적 분석 사각지대 {len(blind)}건 — 수동 확인 필요"},
                {"type": "TextBlock", "wrap": True, "size": "Small", "spacing": "None",
                 "text": "\n".join(
                     f"- {b.get('object_key')} @ {b.get('file','')}:{b.get('line','')} "
                     f"{b.get('reason','')}" for b in blind[:3])},
            ],
        })

    actions: List[Dict[str, Any]] = []
    query = {"mode": "impact", "objects": changed,
             "workspace": report.get("workspace", ""), "hops": 3}
    if app_id:
        actions.append({"type": "Action.OpenUrl", "title": "전체 목록 열기",
                        "url": deep_link(app_id, entity_id, query)})
    elif tab_url:
        actions.append({"type": "Action.OpenUrl", "title": "전체 목록 열기",
                        "url": f"{tab_url}?{urllib.parse.urlencode({'q': json.dumps(query)})}"})

    card: Dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def _fact_list(values: Optional[List[str]]) -> str:
    if not values:
        return "없음"
    head = ", ".join(values[:2])
    return head if len(values) <= 2 else f"{head} 외 {len(values) - 2}건"
