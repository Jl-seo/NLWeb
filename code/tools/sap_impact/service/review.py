"""
Code review payload: a diff that knows what it breaks.

An ordinary diff viewer shows what changed. The thing a SAP reviewer actually
needs to know is what each change reaches -- which programs read the table being
altered, which callers depend on the method being rewritten -- and which added
lines introduce constructs that the impact graph itself cannot follow.

So every changed file arrives with three things attached:
  - its object identity and the objects that depend on it
  - hunks, parsed from git, with added lines annotated
  - annotations that name a real risk in the added line (a new database write, a
    remote call, a dynamic call that becomes a blind spot)

Annotations come from the same patterns the extractor uses, so the review view
and the impact graph never disagree about what a line does.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import model as M
from ..extract_abap import DYNAMIC_PATTERNS, strip_comment
from ..graph import Graph
from ..model import CodeBase
from ..vcs import STATUS_LABEL, FileChange, _git

# (pattern, label, severity) applied to added lines only.
LINE_RULES = [
    (re.compile(r"\b(?:INSERT|MODIFY)\s+[\w/]+\s+FROM\b|\bUPDATE\s+[\w/]+\s+SET\b|\bDELETE\s+FROM\s+[\w/]+", re.I),
     "DB 쓰기 추가", "high"),
    (re.compile(r"\bCOMMIT\s+WORK\b|\bROLLBACK\s+WORK\b", re.I), "트랜잭션 확정/취소", "high"),
    (re.compile(r"\bDESTINATION\b", re.I), "RFC 원격 호출", "high"),
    (re.compile(r"\bCALL\s+FUNCTION\s+'[\w/]+'", re.I), "펑션 호출 추가", "medium"),
    (re.compile(r"\bSELECT\b.*\bFROM\b", re.I), "DB 읽기 추가", "medium"),
    (re.compile(r"\bAUTHORITY-CHECK\b", re.I), "권한 검사", "info"),
    (re.compile(r"\bMESSAGE\s+\w?\d{3}", re.I), "메시지 출력", "info"),
    (re.compile(r"\bSUBMIT\b|\bCALL\s+TRANSACTION\b", re.I), "외부 프로그램 실행", "medium"),
]


@dataclass
class Annotation:
    line: int
    label: str
    severity: str          # high | medium | info | blind
    detail: str = ""


@dataclass
class Hunk:
    header: str
    old_start: int
    new_start: int
    lines: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ReviewFile:
    path: str
    status: str
    object_key: str = ""
    object_type_label: str = ""
    description: str = ""
    added: int = 0
    removed: int = 0
    dependents: List[Dict[str, Any]] = field(default_factory=list)
    hunks: List[Hunk] = field(default_factory=list)
    annotations: List[Annotation] = field(default_factory=list)


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def parse_diff(diff_text: str) -> List[Hunk]:
    """Parse a single file's unified diff into hunks with per-line numbering."""
    hunks: List[Hunk] = []
    current: Optional[Hunk] = None
    old_no = new_no = 0

    for raw in diff_text.splitlines():
        match = _HUNK_RE.match(raw)
        if match:
            old_no = int(match.group(1))
            new_no = int(match.group(3))
            current = Hunk(header=match.group(5).strip(), old_start=old_no, new_start=new_no)
            hunks.append(current)
            continue
        if current is None or raw.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file", "similarity")):
            continue

        kind = raw[:1]
        text = raw[1:]
        if kind == "+":
            current.lines.append({"kind": "add", "new": new_no, "old": None, "text": text})
            new_no += 1
        elif kind == "-":
            current.lines.append({"kind": "del", "new": None, "old": old_no, "text": text})
            old_no += 1
        elif kind == " ":
            current.lines.append({"kind": "ctx", "new": new_no, "old": old_no, "text": text})
            old_no += 1
            new_no += 1
        elif kind == "\\":
            continue
    return hunks


def annotate(hunks: List[Hunk]) -> List[Annotation]:
    """Flag added lines that introduce a real risk. Comments never count."""
    out: List[Annotation] = []
    for hunk in hunks:
        for line in hunk.lines:
            if line["kind"] != "add":
                continue
            code = strip_comment(line["text"])
            if not code.strip():
                continue
            for pattern, reason in DYNAMIC_PATTERNS:
                if pattern.search(code):
                    out.append(Annotation(line=line["new"], label="정적 분석 사각지대",
                                          severity="blind", detail=reason))
                    break
            for pattern, label, severity in LINE_RULES:
                if pattern.search(code):
                    out.append(Annotation(line=line["new"], label=label, severity=severity))
                    break
    return out


def build_review(cb: CodeBase, graph: Graph, changes: List[FileChange],
                 rev_range: Optional[str], max_dependents: int = 8) -> List[ReviewFile]:
    path_to_object = {}
    for key, obj in cb.objects.items():
        for path in obj.paths:
            path_to_object[path.replace("\\", "/").lower()] = key

    files: List[ReviewFile] = []
    for change in changes:
        review = ReviewFile(path=change.path, status=STATUS_LABEL.get(change.status, change.status))
        key = path_to_object.get(change.path.replace("\\", "/").lower())
        if key:
            obj = cb.objects[key]
            review.object_key = key
            review.object_type_label = M.type_label(obj.obj_type)
            review.description = obj.description or ""
            edges = graph.dependents.get(key, [])
            seen = set()
            for edge in edges:
                if edge.source in seen:
                    continue
                seen.add(edge.source)
                source = cb.objects.get(edge.source)
                review.dependents.append({
                    "object_key": edge.source,
                    "object_type_label": M.type_label(source.obj_type) if source else "",
                    "reference_kind": edge.kind,
                    "file": source.paths[0] if source and source.paths else "",
                    "line": edge.line,
                    "statement": edge.snippet,
                })
                if len(review.dependents) >= max_dependents:
                    break

        code, out = _git(cb.root, ["diff", "--unified=5", "--relative",
                                   rev_range or "HEAD", "--", change.path])
        if code == 0 and out.strip():
            review.hunks = parse_diff(out)
            review.annotations = annotate(review.hunks)
            review.added = sum(1 for h in review.hunks for ln in h.lines if ln["kind"] == "add")
            review.removed = sum(1 for h in review.hunks for ln in h.lines if ln["kind"] == "del")
        files.append(review)

    # Files that break the most things belong at the top of a review.
    files.sort(key=lambda f: (-len(f.dependents), -len(f.annotations), f.path))
    return files
