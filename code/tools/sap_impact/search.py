"""
Prompt -> objects.

The customer types a sentence ("구매요청 승인 로직 고치면 뭐가 영향받아?"), not an
object key. This module turns that sentence into concrete objects using lexical
scoring over names, descriptions, paths, tags and, optionally, source text.

It is intentionally not an LLM step: the resolution has to be inspectable, and
the operator must be able to see why ZMM_PR_APPROVE was picked. The LLM comes
after, to explain the impact of what was picked.
"""

import os
import re
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import model as M
from .model import CodeBase

_OBJECT_NAME_RE = re.compile(r"\b(?:/\w+/)?[ZY][A-Z0-9_]{2,}\b", re.I)
_TOKEN_RE = re.compile(r"[A-Za-z가-힣][A-Za-z0-9가-힣_]+")

# Domain vocabulary -> SAP module prefixes commonly used in customer namespaces.
DOMAIN_HINTS = {
    ("구매", "purchase", "po", "구매요청", "pr"): ("MM", "PUR", "PO", "PR"),
    ("판매", "sales", "so", "수주"): ("SD", "SO", "SLS"),
    ("재고", "inventory", "stock", "자재"): ("MM", "INV", "STK"),
    ("회계", "finance", "fi", "전표"): ("FI", "ACC", "GL"),
    ("원가", "controlling", "co"): ("CO", "PC"),
    ("생산", "production", "pp", "작업지시"): ("PP", "PRD"),
    ("품질", "quality", "qm"): ("QM",),
    ("설비", "plant", "pm", "정비"): ("PM",),
    ("인사", "hr", "hcm", "급여"): ("HR", "HCM", "PY"),
}


class Candidate(NamedTuple):
    key: str
    score: float
    why: List[str]


def resolve(cb: CodeBase, prompt: str, limit: int = 10,
            grep_source: bool = True) -> List[Candidate]:
    explicit = {m.group(0).upper() for m in _OBJECT_NAME_RE.finditer(prompt)}
    tokens = [t.lower() for t in _TOKEN_RE.findall(prompt) if len(t) >= 2]
    prefixes = _domain_prefixes(prompt)

    scored: List[Candidate] = []
    for key, obj in cb.objects.items():
        score = 0.0
        why: List[str] = []
        upper_name = obj.name.upper()

        if upper_name in explicit:
            score += 100
            why.append("프롬프트에 오브젝트명 직접 언급")
        else:
            for name in explicit:
                if name in upper_name or upper_name in name:
                    score += 40
                    why.append(f"이름 부분 일치({name})")
                    break

        description = (obj.description or "").lower()
        haystack = " ".join(filter(None, [obj.name, description, " ".join(obj.paths)])).lower()
        matched = [t for t in tokens if t in haystack]
        if matched:
            # A hit in the object's own short text is the strongest lexical signal
            # there is: it is what a functional consultant would have searched.
            in_description = [t for t in matched if t in description]
            score += 6 * len(matched) + 8 * len(in_description)
            why.append(f"키워드 일치: {', '.join(sorted(set(matched))[:4])}"
                       + (f" (설명문 일치: {', '.join(sorted(set(in_description))[:3])})"
                          if in_description else ""))

        for prefix in prefixes:
            if upper_name.lstrip("/").startswith(("Z" + prefix, "Y" + prefix, prefix)):
                score += 8
                why.append(f"업무영역 접두어 {prefix}")
                break

        if score:
            scored.append(Candidate(key, score, why))

    if grep_source and len(scored) < limit:
        scored.extend(_grep(cb, tokens, explicit, existing={c.key for c in scored}))

    scored.sort(key=lambda c: (-c.score, c.key))
    return scored[:limit]


def _domain_prefixes(prompt: str) -> Tuple[str, ...]:
    lower = prompt.lower()
    out: List[str] = []
    for words, prefixes in DOMAIN_HINTS.items():
        if any(w in lower for w in words):
            out.extend(prefixes)
    return tuple(dict.fromkeys(out))


def _grep(cb: CodeBase, tokens: List[str], explicit, existing) -> List[Candidate]:
    """Last resort: look inside the source text for the prompt's keywords."""
    needles = [t for t in tokens if len(t) >= 4] + [e.lower() for e in explicit]
    if not needles:
        return []
    found: List[Candidate] = []
    for key, obj in cb.objects.items():
        if key in existing:
            continue
        for rel in obj.paths[:3]:
            path = os.path.join(cb.root, rel)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read().lower()
            except OSError:
                continue
            hits = [n for n in needles if n in text]
            if hits:
                found.append(Candidate(key, 3.0 * len(hits),
                                       [f"소스 내 문자열 일치: {', '.join(sorted(set(hits))[:3])}"]))
                break
    return found
