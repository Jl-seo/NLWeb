"""
Incident back-trace: from a symptom to the recent changes that could explain it.

The question a development lead asks when production breaks is not "what does
this object reach" but the reverse: "something is wrong in ZORDER -- which of
the changes we shipped this month could have done that?"

Static analysis answers it in three steps, each of them deterministic:

  1. resolve the symptom (a transaction, a program, a table, or a phrase) to
     objects in the code base
  2. walk *forward* from those objects: everything they depend on, because a
     failure in X is caused by a change in X or in something X uses
  3. intersect that closure with the objects touched by commits in the window,
     and rank what is left by distance from the symptom and by recency

What comes out is a short list with commit, author, date and the path from the
symptom to the change -- the list a lead would otherwise assemble by calling
developers into a room.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import model as M
from . import search as search_mod
from . import vcs
from .graph import Graph
from .model import CodeBase

# Types whose change is a stronger suspect for a runtime failure than a report
# edit: DDIC changes reach every reader through the data, silently.
DATA_LAYER_BONUS = 2.0
EXTERNAL_BONUS = 1.0


@dataclass
class Candidate:
    object_key: str
    object_type_label: str
    description: str
    hops: int                       # 0 = the symptom object itself
    path: List[str]                 # symptom -> ... -> changed object
    commits: List[Dict[str, str]]   # commit, author, date, subject, status
    score: float
    reasons: List[str] = field(default_factory=list)
    blind_spots: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object_key": self.object_key,
            "object_type_label": self.object_type_label,
            "description": self.description,
            "hops": self.hops,
            "path": self.path,
            "commits": self.commits,
            "score": round(self.score, 1),
            "reasons": self.reasons,
            "blind_spots": self.blind_spots,
        }


@dataclass
class IncidentReport:
    symptom: str
    since: str
    symptom_objects: List[Dict[str, Any]] = field(default_factory=list)
    candidates: List[Candidate] = field(default_factory=list)
    commits_in_window: int = 0
    changed_objects_in_window: int = 0
    unrelated_changes: int = 0
    blind_spots_on_path: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symptom": self.symptom,
            "since": self.since,
            "symptom_objects": self.symptom_objects,
            "candidates": [c.to_dict() for c in self.candidates],
            "commits_in_window": self.commits_in_window,
            "changed_objects_in_window": self.changed_objects_in_window,
            "unrelated_changes": self.unrelated_changes,
            "blind_spots_on_path": self.blind_spots_on_path,
            "notes": self.notes,
        }


def trace(cb: CodeBase, graph: Graph, symptom: str, since: str = "14 days ago",
          max_hops: int = 4, select: int = 3, limit: int = 15) -> IncidentReport:
    report = IncidentReport(symptom=symptom, since=since)

    # 1. symptom -> objects
    candidates = search_mod.resolve(cb, symptom, limit=max(select, 5))
    picked = [c.key for c in candidates[:select]]
    roots = _expand_transactions(cb, graph, picked)
    report.symptom_objects = [
        {"object_key": c.key, "matched_because": "; ".join(c.why)} for c in candidates[:select]
    ] + [
        # A transaction code holds no logic; the program behind it is where the
        # failure actually lives, so it joins the symptom set explicitly.
        {"object_key": key, "matched_because": "증상 트랜잭션이 실행하는 프로그램"}
        for key in roots if key not in picked
    ]
    if not roots:
        report.notes.append(
            "증상을 코드베이스의 오브젝트로 연결하지 못했습니다. 트랜잭션·프로그램·테이블명을 지정해 주세요.")
        return report

    # 2. forward closure with distance and path
    distance: Dict[str, int] = {r: 0 for r in roots}
    path: Dict[str, List[str]] = {r: [r] for r in roots}
    for hit in graph.depends_on(roots, max_hops=max_hops):
        if hit.key not in distance or hit.hops < distance[hit.key]:
            distance[hit.key] = hit.hops
            path[hit.key] = list(hit.via)

    # 3. recent changes, mapped to objects
    commits = vcs.commits_since(cb.root, since)
    report.commits_in_window = len(commits)
    touched: Dict[str, List[Dict[str, str]]] = {}
    for commit in commits:
        keys, _ = vcs.map_files_to_objects(cb, commit.files)
        statuses = {c.path.replace("\\\\", "/").lower(): c.status for c in commit.files}
        for key in keys:
            obj = cb.objects[key]
            status = next((statuses.get(p.replace("\\\\", "/").lower(), "M") for p in obj.paths), "M")
            touched.setdefault(key, []).append({
                "commit": commit.commit, "author": commit.author, "date": commit.date,
                "subject": commit.subject, "status": vcs.STATUS_LABEL.get(status, status),
            })
    report.changed_objects_in_window = len(touched)

    # 4. intersect and rank
    for key, commit_list in touched.items():
        if key not in distance:
            continue
        obj = cb.objects[key]
        hops = distance[key]
        score = 10.0 - 2.0 * hops
        reasons: List[str] = []
        if hops == 0:
            reasons.append("증상 오브젝트 자체가 변경됨")
        else:
            reasons.append(f"증상 오브젝트가 {hops}홉 거리에서 이 오브젝트에 의존")
        if obj.obj_type in M.DATA_LAYER_TYPES:
            score += DATA_LAYER_BONUS
            reasons.append("DDIC 변경 — 읽는 모든 코드에 데이터로 조용히 전파")
        if obj.obj_type in M.EXTERNAL_CONTRACT_TYPES:
            score += EXTERNAL_BONUS
            reasons.append("외부 계약 오브젝트")
        if len(commit_list) > 1:
            score += 0.5 * (len(commit_list) - 1)
            reasons.append(f"기간 내 {len(commit_list)}회 변경")
        latest = max(c["date"] for c in commit_list)
        reasons.append(f"최근 변경 {latest}")
        spots = len(cb.blind_spots.get(key, []))
        if spots:
            score += 1.0
            reasons.append(f"동적 호출 {spots}건 — 정적으로 못 보는 경로 존재")
        report.candidates.append(Candidate(
            object_key=key, object_type_label=M.type_label(obj.obj_type),
            description=obj.description or "", hops=hops, path=path[key],
            commits=sorted(commit_list, key=lambda c: c["date"], reverse=True),
            score=score, reasons=reasons, blind_spots=spots,
        ))

    report.candidates.sort(key=lambda c: (-c.score, c.hops, c.object_key))
    report.candidates = report.candidates[:limit]
    report.unrelated_changes = len(touched) - len(report.candidates)

    # 5. honesty: dynamic calls anywhere on the symptom's closure mean the
    #    closure may be incomplete, so a change outside it is not ruled out.
    for key in distance:
        for spot in cb.blind_spots.get(key, []):
            report.blind_spots_on_path.append({"object_key": key, **spot})
    if report.blind_spots_on_path:
        report.notes.append(
            f"증상 오브젝트의 의존 경로에 동적 호출 {len(report.blind_spots_on_path)}건이 있어 "
            "후보 목록 밖의 변경도 원인일 수 있습니다.")
    if not report.candidates and touched:
        report.notes.append(
            f"기간 내 변경 {len(touched)}건 중 증상 오브젝트의 의존 경로에 있는 것이 없습니다. "
            "기간을 넓히거나(since) 추적 깊이(max_hops)를 늘려 보세요.")
    if not commits:
        report.notes.append("기간 내 커밋이 없습니다. git 이력이 있는 코드베이스인지 확인하세요.")
    return report


def _expand_transactions(cb: CodeBase, graph: Graph, keys: List[str]) -> List[str]:
    out = list(keys)
    for key in keys:
        obj = cb.objects.get(key)
        if obj and obj.obj_type == M.TRANSACTION:
            for edge in graph.dependencies.get(key, []):
                if edge.kind == "TRANSACTION_PROGRAM" and edge.target not in out:
                    out.append(edge.target)
    return out
