"""
Period summary: what changed, how risky it was, in one page.

A lead reports upward on change management: how many changes went out, how
many were risky, how many touched an interface someone else depends on. Today
that is a spreadsheet assembled by hand. Here every commit in the window is run
through the same impact analysis a single change gets, and the results are
counted. The narrative on top is the agent's job; this module supplies numbers
it is not allowed to invent.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from . import model as M
from . import vcs
from .graph import Graph
from .impact import analyze
from .model import CodeBase

SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass
class CommitDigest:
    commit: str
    author: str
    date: str
    subject: str
    changed_objects: List[str]
    severity: str
    impacted_count: int
    external_contracts: List[str]
    blind_spots: int
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


@dataclass
class PeriodSummary:
    since: str
    commits: int = 0
    commits_with_sap_objects: int = 0
    changed_objects: int = 0
    by_severity: Dict[str, int] = field(default_factory=lambda: {s: 0 for s in SEVERITY_ORDER})
    by_type: List[Dict[str, Any]] = field(default_factory=list)
    by_author: List[Dict[str, Any]] = field(default_factory=list)
    external_contracts_touched: List[str] = field(default_factory=list)
    hotspots_touched: List[Dict[str, Any]] = field(default_factory=list)
    blind_spots_touched: int = 0
    high_risk: List[CommitDigest] = field(default_factory=list)
    all_commits: List[CommitDigest] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self, include_all: bool = False) -> Dict[str, Any]:
        out = {
            "since": self.since,
            "commits": self.commits,
            "commits_with_sap_objects": self.commits_with_sap_objects,
            "changed_objects": self.changed_objects,
            "by_severity": self.by_severity,
            "by_type": self.by_type,
            "by_author": self.by_author,
            "external_contracts_touched": self.external_contracts_touched,
            "hotspots_touched": self.hotspots_touched,
            "blind_spots_touched": self.blind_spots_touched,
            "high_risk": [c.to_dict() for c in self.high_risk],
            "notes": self.notes,
        }
        if include_all:
            out["all_commits"] = [c.to_dict() for c in self.all_commits]
        return out


def summarize(cb: CodeBase, graph: Graph, since: str = "7 days ago",
              max_hops: int = 2, top: int = 5, hotspot_fan_in: int = 5) -> PeriodSummary:
    summary = PeriodSummary(since=since)
    commits = vcs.commits_since(cb.root, since)
    summary.commits = len(commits)
    if not commits:
        summary.notes.append("기간 내 커밋이 없습니다.")
        return summary

    changed_all: Dict[str, int] = {}
    type_counts: Dict[str, int] = {}
    author_counts: Dict[str, Dict[str, int]] = {}
    externals: set = set()

    for commit in commits:
        keys, _ = vcs.map_files_to_objects(cb, commit.files)
        if not keys:
            continue
        summary.commits_with_sap_objects += 1
        report = analyze(cb, graph, keys, max_hops=max_hops, include_forward=False)
        digest = CommitDigest(
            commit=commit.commit, author=commit.author, date=commit.date, subject=commit.subject,
            changed_objects=keys, severity=report.severity,
            impacted_count=len(report.impacted),
            external_contracts=list(report.external_contracts),
            blind_spots=len(report.blind_spots), reasons=list(report.reasons),
        )
        summary.all_commits.append(digest)
        summary.by_severity[report.severity] = summary.by_severity.get(report.severity, 0) + 1
        externals.update(report.external_contracts)
        stats = author_counts.setdefault(commit.author, {"commits": 0, "high_risk": 0})
        stats["commits"] += 1
        if report.severity in ("HIGH", "CRITICAL"):
            stats["high_risk"] += 1
        for key in keys:
            changed_all[key] = changed_all.get(key, 0) + 1
            obj_type = cb.objects[key].obj_type
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

    summary.changed_objects = len(changed_all)
    summary.by_type = [{"type": t, "label": M.type_label(t), "count": c}
                       for t, c in sorted(type_counts.items(), key=lambda x: -x[1])]
    summary.by_author = [{"author": a, **c} for a, c in
                         sorted(author_counts.items(), key=lambda x: -x[1]["commits"])]
    summary.external_contracts_touched = sorted(externals)
    summary.blind_spots_touched = sum(len(cb.blind_spots.get(k, [])) for k in changed_all)

    for key, times in changed_all.items():
        fan_in = graph.fan_in(key)
        if fan_in >= hotspot_fan_in:
            obj = cb.objects[key]
            summary.hotspots_touched.append({
                "object_key": key, "object_type_label": M.type_label(obj.obj_type),
                "dependents": fan_in, "times_changed": times,
            })
    summary.hotspots_touched.sort(key=lambda h: -h["dependents"])

    ranked = sorted(summary.all_commits,
                    key=lambda d: (-SEVERITY_ORDER.index(d.severity), -d.impacted_count))
    summary.high_risk = [d for d in ranked if d.severity in ("HIGH", "CRITICAL")][:top] or ranked[:top]

    if summary.commits_with_sap_objects < summary.commits:
        summary.notes.append(
            f"커밋 {summary.commits}건 중 {summary.commits - summary.commits_with_sap_objects}건은 "
            "SAP 개발 오브젝트를 건드리지 않아 집계에서 제외했습니다.")
    return summary
