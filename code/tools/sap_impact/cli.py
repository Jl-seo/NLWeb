"""
Command line entry point.

    python -m tools.sap_impact.cli scan      <dir>
    python -m tools.sap_impact.cli impact    <dir> --objects ZCL_ORDER,ZTORDER
    python -m tools.sap_impact.cli changes   <dir> --rev HEAD~1 --explain
    python -m tools.sap_impact.cli ask       <dir> "구매요청 승인 로직 고치면 뭐가 영향받아?"
    python -m tools.sap_impact.cli where-used <dir> --object ZCL_ORDER

Run from the repository's `code/` directory so that the NLWeb LLM layer
(llm/llm.py, config/) is importable when --explain is used.
"""

import argparse
import json
import os
import sys
from typing import List, Optional

if __package__ in (None, ""):  # allow `python cli.py` from inside the folder
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "sap_impact"

from . import model as M
from . import search as search_mod
from . import vcs
from .graph import Graph
from .impact import analyze, ImpactReport
from .model import CodeBase
from .scanner import scan

SEVERITY_MARK = {"LOW": "낮음", "MEDIUM": "보통", "HIGH": "높음", "CRITICAL": "매우 높음"}


# ------------------------------------------------------------------ plumbing


def _load_codebase(args) -> CodeBase:
    if getattr(args, "index", None) and os.path.exists(args.index):
        with open(args.index, "r", encoding="utf-8") as fh:
            cb = CodeBase.from_dict(json.load(fh))
        print(f"[index] {args.index} 재사용 — 오브젝트 {len(cb.objects)}건")
        return cb

    cb = scan(args.directory, verbose=getattr(args, "verbose", False))
    if getattr(args, "index", None):
        with open(args.index, "w", encoding="utf-8") as fh:
            json.dump(cb.to_dict(), fh, ensure_ascii=False, indent=1)
        print(f"[index] {args.index} 저장")
    return cb


def _resolve_keys(cb: CodeBase, tokens: List[str]) -> List[str]:
    """Accept 'CLAS/ZCL_X', 'ZCL_X' or 'zcl_x' and return canonical keys."""
    keys: List[str] = []
    by_name = {}
    for key, obj in cb.objects.items():
        by_name.setdefault(obj.name.upper(), []).append(key)

    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token in cb.objects:
            keys.append(token)
            continue
        hits = by_name.get(token.upper(), [])
        if hits:
            keys.extend(hits)
        else:
            keys.append(token)  # kept, reported as 'missing' by the analyzer
    return list(dict.fromkeys(keys))


def _expand_selection(cb: CodeBase, graph: Graph, keys: List[str]) -> List[str]:
    """
    A transaction code holds no logic -- the program behind it does. When the
    prompt resolves to a TRAN, pull in the program it starts, otherwise the
    analysis reports on an empty shell.
    """
    expanded = list(keys)
    for key in keys:
        obj = cb.objects.get(key)
        if not obj or obj.obj_type != M.TRANSACTION:
            continue
        for edge in graph.dependencies.get(key, []):
            if edge.kind == "TRANSACTION_PROGRAM" and edge.target not in expanded:
                expanded.append(edge.target)
    return expanded


# ------------------------------------------------------------------ rendering


def _print_report(cb: CodeBase, report: ImpactReport, show_paths: bool = True) -> None:
    print()
    print("=" * 78)
    print(f" 변경 영향 분석 결과   위험도: {report.severity} ({SEVERITY_MARK.get(report.severity, '')})")
    print("=" * 78)

    print("\n[변경 오브젝트]")
    for key in report.changed:
        obj = cb.objects[key]
        desc = f" — {obj.description}" if obj.description else ""
        tags = f"  [{', '.join(sorted(obj.tags))}]" if obj.tags else ""
        print(f"  {key:<38} {M.type_label(obj.obj_type)}{desc}{tags}")
        for path in obj.paths[:3]:
            print(f"      {path}")
    for key in report.missing:
        print(f"  {key:<38} (코드베이스에서 찾지 못함)")

    print("\n[판정 근거]")
    for reason in report.reasons:
        print(f"  - {reason}")

    print(f"\n[영향 오브젝트] 총 {len(report.impacted)}건 (최대 {report.max_hops}홉)")
    if not report.impacted:
        print("  없음 — 이 코드베이스 내 참조자가 없습니다.")
    for hit in report.impacted:
        obj = cb.objects.get(hit.key)
        label = M.type_label(obj.obj_type) if obj else "?"
        print(f"  [{hit.hops}홉] {hit.key:<34} {label}")
        if show_paths:
            print(f"        경로: {' -> '.join(hit.via)}")
            if hit.edge:
                src_paths = cb.objects[hit.edge.source].paths[:1] if hit.edge.source in cb.objects else []
                where = f"{src_paths[0]}:{hit.edge.line}" if src_paths else f"line {hit.edge.line}"
                print(f"        근거: {hit.kinds[-1]} @ {where}")
                print(f"              {hit.edge.snippet[:110]}")

    if report.external_contracts:
        print("\n[외부 계약 도달] 연계 시스템·사용자 화면에 노출되는 오브젝트")
        for key in report.external_contracts:
            print(f"  - {key}")

    if report.test_scope:
        print("\n[회귀 테스트 후보] 실행 가능한 단위")
        for item in report.test_scope:
            print(f"  - {item}")

    if report.blind_spots:
        print(f"\n[정적 분석 사각지대] {len(report.blind_spots)}건 — 그래프에 안 잡히는 호출, 수동 확인 필요")
        for spot in report.blind_spots[:15]:
            print(f"  - {spot['object']} @ {spot.get('file','')}:{spot['line']}  {spot['reason']}")
        if len(report.blind_spots) > 15:
            print(f"  ... 외 {len(report.blind_spots) - 15}건")


def _maybe_explain(cb: CodeBase, report: ImpactReport, args, prompt: str = "",
                   diff_text: str = "") -> None:
    if not getattr(args, "explain", False):
        return
    from . import explain as explain_mod

    if getattr(args, "dry_run", False):
        print("\n" + "=" * 78)
        print(" LLM 프롬프트 (전송하지 않음, --dry-run)")
        print("=" * 78)
        print(explain_mod.build_prompt(cb, report, prompt, diff_text))
        return

    print("\n" + "=" * 78)
    print(" LLM 영향도 설명")
    print("=" * 78)
    try:
        result = explain_mod.explain(cb, report, prompt, diff_text,
                                     provider=args.provider, level=args.level)
    except RuntimeError as exc:
        print(f"  {exc}")
        print("  (--dry-run 으로 프롬프트만 확인하거나, config/config_llm.yaml 및 API 키를 확인하세요)")
        return
    print(explain_mod.render(result))


# ------------------------------------------------------------------ commands


def cmd_scan(args) -> int:
    cb = _load_codebase(args)
    graph = Graph(cb)

    by_type = {}
    for obj in cb.objects.values():
        by_type[obj.obj_type] = by_type.get(obj.obj_type, 0) + 1

    print(f"\n[스캔] {cb.root}")
    print(f"  오브젝트 {len(cb.objects)}건 / 참조 엣지 {len(cb.references)}건 / "
          f"미해결 참조 {len(cb.unresolved)}건")
    print("\n[오브젝트 타입별]")
    for obj_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {M.type_label(obj_type):<18} {count:>5}   ({obj_type})")

    print("\n[참조 집중 오브젝트] 변경 시 파급이 큰 순서")
    for key, fan_in in graph.hotspots(limit=15):
        obj = cb.objects[key]
        print(f"  {key:<38} 참조자 {fan_in:>4}건   {M.type_label(obj.obj_type)}")

    if cb.blind_spots:
        total = sum(len(v) for v in cb.blind_spots.values())
        print(f"\n[정적 분석 사각지대] {total}건 / {len(cb.blind_spots)} 오브젝트")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(cb.to_dict(), fh, ensure_ascii=False, indent=1)
        print(f"\n[출력] {args.json}")
    return 0


def cmd_impact(args) -> int:
    cb = _load_codebase(args)
    graph = Graph(cb)
    keys = _resolve_keys(cb, args.objects.split(","))
    report = analyze(cb, graph, keys, max_hops=args.hops)
    _print_report(cb, report, show_paths=not args.brief)
    _maybe_explain(cb, report, args, prompt=args.prompt or "")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(cb), fh, ensure_ascii=False, indent=1)
        print(f"\n[출력] {args.json}")
    return 0


def cmd_changes(args) -> int:
    cb = _load_codebase(args)
    graph = Graph(cb)
    try:
        changes = vcs.changed_files(cb.root, rev_range=args.rev, since=args.since)
    except RuntimeError as exc:
        print(f"[오류] {exc}")
        return 2

    if not changes:
        print("[수정내역] 변경된 파일이 없습니다.")
        return 0

    print(f"\n[수정내역] {args.rev or '작업트리(uncommitted)'} 기준 {len(changes)}개 파일")
    for change in changes:
        print(f"  {vcs.STATUS_LABEL.get(change.status, change.status)}  {change.path}")

    keys, unmapped = vcs.map_files_to_objects(cb, changes)
    if unmapped:
        print(f"\n  (SAP 오브젝트로 매핑되지 않은 파일 {len(unmapped)}건: "
              f"{', '.join(c.path for c in unmapped[:5])}{' ...' if len(unmapped) > 5 else ''})")
    if not keys:
        print("\n[영향 분석] 변경 파일이 SAP 개발 오브젝트가 아니어서 분석을 건너뜁니다.")
        return 0

    if args.history:
        print("\n[변경 이력]")
        for change in changes[:10]:
            for entry in vcs.file_history(cb.root, change.path, limit=args.history):
                print(f"  {entry.date}  {entry.commit}  {entry.author:<16} {entry.subject}")

    report = analyze(cb, graph, keys, max_hops=args.hops)
    _print_report(cb, report, show_paths=not args.brief)

    diff_text = ""
    if args.explain:
        code, out = vcs._git(cb.root, ["diff", args.rev or "HEAD", "--unified=3"])
        diff_text = out if code == 0 else ""
    _maybe_explain(cb, report, args, prompt=args.prompt or "", diff_text=diff_text)
    return 0


def cmd_ask(args) -> int:
    cb = _load_codebase(args)
    graph = Graph(cb)
    candidates = search_mod.resolve(cb, args.prompt_text, limit=args.top)
    if not candidates:
        print(f"[검색] '{args.prompt_text}' 에 해당하는 오브젝트를 찾지 못했습니다.")
        print("       오브젝트명(Z*)을 포함하거나, scan 결과에서 이름을 확인해 주세요.")
        return 1

    print(f"\n[프롬프트 해석] '{args.prompt_text}'")
    for cand in candidates:
        obj = cb.objects[cand.key]
        print(f"  {cand.score:>6.1f}  {cand.key:<36} {M.type_label(obj.obj_type)}")
        for why in cand.why:
            print(f"          · {why}")

    selected = _expand_selection(cb, graph, [c.key for c in candidates[: args.select]])
    print(f"\n[분석 대상] 상위 {args.select}건 + 연결 오브젝트: {', '.join(selected)}")

    report = analyze(cb, graph, selected, max_hops=args.hops)
    _print_report(cb, report, show_paths=not args.brief)
    _maybe_explain(cb, report, args, prompt=args.prompt_text)
    return 0


def cmd_where_used(args) -> int:
    cb = _load_codebase(args)
    graph = Graph(cb)
    keys = _resolve_keys(cb, [args.object])
    for key in keys:
        if key not in cb.objects:
            print(f"[미발견] {key}")
            continue
        obj = cb.objects[key]
        print(f"\n[{key}] {M.type_label(obj.obj_type)}  파일: {', '.join(obj.paths[:3])}")
        edges = graph.dependents.get(key, [])
        print(f"  직접 참조자 {len({e.source for e in edges})}건")
        for edge in sorted(edges, key=lambda e: (e.source, e.line)):
            src_paths = cb.objects[edge.source].paths[:1] if edge.source in cb.objects else []
            where = f"{src_paths[0]}:{edge.line}" if src_paths else f"line {edge.line}"
            print(f"    {edge.source:<36} {edge.kind:<20} {where}")
            print(f"        {edge.snippet[:110]}")
        out_edges = graph.dependencies.get(key, [])
        print(f"  이 오브젝트가 사용하는 대상 {len({e.target for e in out_edges})}건")
        for edge in sorted(out_edges, key=lambda e: (e.target, e.line))[:30]:
            print(f"    -> {edge.target:<33} {edge.kind}")
    return 0


# ---------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sap_impact",
        description="SAP(ABAP/BTP) 코드 변경 영향 분석 — 참조 그래프(결정론) + LLM 설명",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, need_dir=True):
        if need_dir:
            p.add_argument("directory", help="SAP 코드 디렉토리 (abapGit export 또는 BTP 프로젝트)")
        p.add_argument("--index", help="스캔 결과 JSON 캐시 경로 (있으면 재사용, 없으면 생성)")
        p.add_argument("--hops", type=int, default=3, help="영향 추적 최대 홉 수 (기본 3)")
        p.add_argument("--brief", action="store_true", help="참조 경로·근거 코드 생략")
        p.add_argument("--explain", action="store_true", help="LLM으로 영향도 설명 생성")
        p.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 프롬프트만 출력")
        p.add_argument("--provider", help="LLM 프로바이더 (기본: config_llm.yaml preferred_provider)")
        p.add_argument("--level", default="high", choices=["low", "high"], help="모델 등급")
        p.add_argument("--json", help="결과 JSON 저장 경로")
        p.add_argument("--verbose", action="store_true")

    p_scan = sub.add_parser("scan", help="디렉토리 스캔 — 오브젝트 분류 및 참조 그래프 통계")
    common(p_scan)
    p_scan.set_defaults(func=cmd_scan)

    p_impact = sub.add_parser("impact", help="지정 오브젝트 변경의 영향 분석")
    common(p_impact)
    p_impact.add_argument("--objects", required=True, help="변경 오브젝트, 쉼표 구분 (ZCL_X 또는 CLAS/ZCL_X)")
    p_impact.add_argument("--prompt", help="LLM에 함께 전달할 질문/맥락")
    p_impact.set_defaults(func=cmd_impact)

    p_changes = sub.add_parser("changes", help="git 수정내역 기반 영향 분석")
    common(p_changes)
    p_changes.add_argument("--rev", help="git 리비전 범위 (예: HEAD~1, main..feature). 생략 시 작업트리")
    p_changes.add_argument("--since", help="git --since 필터 (예: '2 weeks ago')")
    p_changes.add_argument("--history", type=int, default=0, help="파일별 커밋 이력 N건 표시")
    p_changes.add_argument("--prompt", help="LLM에 함께 전달할 질문/맥락")
    p_changes.set_defaults(func=cmd_changes)

    p_ask = sub.add_parser("ask", help="자연어 프롬프트로 대상을 찾아 영향 분석")
    common(p_ask)
    p_ask.add_argument("prompt_text", help="예: '구매요청 승인 로직 바꾸면 뭐가 영향받아?'")
    p_ask.add_argument("--top", type=int, default=8, help="후보 표시 개수")
    p_ask.add_argument("--select", type=int, default=2, help="상위 N건을 분석 대상으로 사용")
    p_ask.set_defaults(func=cmd_ask)

    p_where = sub.add_parser("where-used", help="단일 오브젝트의 사용처 목록 (SE84 대응)")
    common(p_where)
    p_where.add_argument("--object", required=True, help="오브젝트명 또는 키")
    p_where.set_defaults(func=cmd_where_used)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not os.path.isdir(args.directory):
        print(f"[오류] 디렉토리를 찾을 수 없습니다: {args.directory}")
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
