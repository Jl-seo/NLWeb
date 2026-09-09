"""
Workspace management for the hosted service.

A workspace is one SAP code base (an abapGit mirror, a BTP project) that the
service keeps an index for. Scanning tens of thousands of objects takes minutes,
so it never happens inside a request: the index is built once, cached on disk,
and every query is served from memory.

Sources supported:
  local  - a directory already present on the container (mounted share, sidecar)
  git    - a repository cloned and pulled on refresh (abapGit mirror in
           Azure DevOps or GitHub)
"""

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import vcs
from ..graph import Graph
from ..model import CodeBase
from ..scanner import scan

DEFAULT_CACHE_DIR = os.environ.get("SAP_IMPACT_CACHE", "/tmp/sap-impact-cache")
DEFAULT_WORKSPACE_FILE = os.environ.get("SAP_IMPACT_WORKSPACES", "")


@dataclass
class WorkspaceConfig:
    id: str
    kind: str                      # "local" | "git"
    path: str = ""                 # local directory (kind=local, or clone target)
    url: str = ""                  # git remote (kind=git)
    branch: str = ""
    description: str = ""


@dataclass
class WorkspaceState:
    config: WorkspaceConfig
    codebase: Optional[CodeBase] = None
    graph: Optional[Graph] = None
    indexed_at: float = 0.0
    indexing: bool = False
    last_error: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.codebase is not None and self.graph is not None


class WorkspaceRegistry:
    """Thread-safe registry. Indexing runs in a worker thread, queries never block."""

    def __init__(self, configs: List[WorkspaceConfig], cache_dir: str = DEFAULT_CACHE_DIR):
        self._states: Dict[str, WorkspaceState] = {c.id: WorkspaceState(config=c) for c in configs}
        self._lock = threading.Lock()
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------ read

    def ids(self) -> List[str]:
        return list(self._states)

    def get(self, workspace_id: Optional[str]) -> WorkspaceState:
        if not workspace_id:
            if len(self._states) != 1:
                raise KeyError(
                    "workspace 를 지정해야 합니다. 등록된 workspace: " + ", ".join(self._states)
                )
            workspace_id = next(iter(self._states))
        if workspace_id not in self._states:
            raise KeyError(f"알 수 없는 workspace '{workspace_id}'. 등록된 값: {', '.join(self._states)}")
        return self._states[workspace_id]

    def require_ready(self, workspace_id: Optional[str]) -> WorkspaceState:
        state = self.get(workspace_id)
        if not state.ready:
            if state.indexing:
                raise RuntimeError(f"workspace '{state.config.id}' 인덱싱 진행 중입니다. 잠시 후 다시 시도하세요.")
            if state.last_error:
                raise RuntimeError(f"workspace '{state.config.id}' 인덱싱 실패: {state.last_error}")
            raise RuntimeError(f"workspace '{state.config.id}' 가 아직 인덱싱되지 않았습니다.")
        return state

    def describe(self) -> List[Dict[str, Any]]:
        out = []
        for state in self._states.values():
            out.append({
                "id": state.config.id,
                "kind": state.config.kind,
                "description": state.config.description,
                "ready": state.ready,
                "indexing": state.indexing,
                "indexed_at": _iso(state.indexed_at),
                "last_error": state.last_error,
                **state.stats,
            })
        return out

    # ----------------------------------------------------------------- write

    def load_cached_all(self) -> None:
        for state in self._states.values():
            path = self._cache_path(state.config.id)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    cb = CodeBase.from_dict(json.load(fh))
                self._install(state, cb, os.path.getmtime(path))
            except (OSError, ValueError) as exc:
                state.last_error = f"캐시 로드 실패: {exc}"

    def reindex(self, workspace_id: str, background: bool = True) -> None:
        state = self.get(workspace_id)
        with self._lock:
            if state.indexing:
                return
            state.indexing = True
        if background:
            threading.Thread(target=self._reindex_worker, args=(state,), daemon=True).start()
        else:
            self._reindex_worker(state)

    def _reindex_worker(self, state: WorkspaceState) -> None:
        try:
            root = self._materialize(state.config)
            cb = scan(root)
            self._install(state, cb, time.time())
            state.last_error = ""
            try:
                with open(self._cache_path(state.config.id), "w", encoding="utf-8") as fh:
                    json.dump(cb.to_dict(), fh, ensure_ascii=False)
            except OSError as exc:
                state.last_error = f"캐시 저장 실패(분석은 정상): {exc}"
        except Exception as exc:  # a failed index must not take the service down
            state.last_error = str(exc)
        finally:
            state.indexing = False

    def _install(self, state: WorkspaceState, cb: CodeBase, when: float) -> None:
        graph = Graph(cb)
        with self._lock:
            state.codebase = cb
            state.graph = graph
            state.indexed_at = when
            state.stats = {
                "objects": len(cb.objects),
                "references": len(cb.references),
                "unresolved": len(cb.unresolved),
                "blind_spot_objects": len(cb.blind_spots),
            }

    def _materialize(self, config: WorkspaceConfig) -> str:
        if config.kind == "local":
            if not os.path.isdir(config.path):
                raise RuntimeError(f"디렉토리를 찾을 수 없습니다: {config.path}")
            return config.path

        if config.kind == "git":
            target = config.path or os.path.join(self.cache_dir, f"repo-{config.id}")
            if os.path.isdir(os.path.join(target, ".git")):
                _run(["git", "-C", target, "fetch", "--prune", "origin"])
                branch = config.branch or _default_branch(target)
                _run(["git", "-C", target, "checkout", branch])
                _run(["git", "-C", target, "reset", "--hard", f"origin/{branch}"])
            else:
                args = ["git", "clone"]
                if config.branch:
                    args += ["--branch", config.branch]
                args += [config.url, target]
                _run(args)
            return target

        raise RuntimeError(f"지원하지 않는 workspace kind: {config.kind}")

    def _cache_path(self, workspace_id: str) -> str:
        return os.path.join(self.cache_dir, f"index-{workspace_id}.json")


# --------------------------------------------------------------------- config


def load_configs() -> List[WorkspaceConfig]:
    """
    Workspaces come from SAP_IMPACT_WORKSPACES (a JSON file path or inline JSON
    array), or from SAP_IMPACT_PATH for the single-directory case.
    """
    raw = DEFAULT_WORKSPACE_FILE
    if raw:
        if os.path.exists(raw):
            with open(raw, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        else:
            data = json.loads(raw)
        return [WorkspaceConfig(**item) for item in data]

    path = os.environ.get("SAP_IMPACT_PATH")
    if path:
        return [WorkspaceConfig(id="default", kind="local", path=path,
                                description="SAP_IMPACT_PATH 로 지정된 코드 디렉토리")]

    url = os.environ.get("SAP_IMPACT_GIT_URL")
    if url:
        return [WorkspaceConfig(id="default", kind="git", url=url,
                                branch=os.environ.get("SAP_IMPACT_GIT_BRANCH", ""),
                                description="abapGit 미러 저장소")]
    return []


def _run(args: List[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} 실패: {(proc.stderr or proc.stdout).strip()[:400]}")
    return proc.stdout


def _default_branch(repo: str) -> str:
    code, out = vcs._git(repo, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if code == 0 and "/" in out:
        return out.strip().split("/")[-1]
    return "main"


def _iso(ts: float) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
