"""
Change history ("수정내역") from the git mirror of the abapGit export.

abapGit gives every SAP object a stable file path, so a git range answers
"what changed" precisely: no transport request parsing, no version-database
access. If the directory is not a git repository the caller falls back to naming
the changed objects manually.
"""

import os
import subprocess
from typing import Dict, List, NamedTuple, Optional, Tuple

from .model import CodeBase


class FileChange(NamedTuple):
    status: str      # A / M / D / R
    path: str        # repo-relative
    commit: str = ""
    author: str = ""
    date: str = ""
    subject: str = ""


STATUS_LABEL = {"A": "추가", "M": "수정", "D": "삭제", "R": "이름변경", "C": "복사"}


def is_git_repo(root: str) -> bool:
    return _git(root, ["rev-parse", "--is-inside-work-tree"])[0] == 0


def changed_files(root: str, rev_range: Optional[str] = None,
                  since: Optional[str] = None) -> List[FileChange]:
    """
    `rev_range` is anything git understands (HEAD~1, main..feature, a tag range).
    Without it, uncommitted working-tree changes are used, which is what a
    developer wants while still editing.
    """
    if not is_git_repo(root):
        raise RuntimeError(f"{root} 는 git 저장소가 아닙니다. --objects 로 변경 오브젝트를 직접 지정하세요.")

    # --relative makes paths relative to `root` and scopes the diff to it, so a
    # code directory nested inside a larger repository still maps cleanly onto
    # the object paths recorded by the scanner.
    args = ["diff", "--name-status", "--find-renames", "--relative"]
    if since:
        args += [f"--since={since}"]
    if rev_range:
        args += [rev_range]
    else:
        args += ["HEAD"]

    code, out = _git(root, args)
    if code != 0:
        raise RuntimeError(f"git diff 실패: {out.strip()}")

    changes: List[FileChange] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0]
        path = parts[-1]
        changes.append(FileChange(status=status, path=path))
    return changes


def file_history(root: str, path: str, limit: int = 10) -> List[FileChange]:
    """Commit history for one file -- the 'who touched this and why' answer."""
    code, out = _git(root, [
        "log", f"-{limit}", "--follow", "--date=short",
        "--pretty=format:%h%x09%an%x09%ad%x09%s", "--", path,
    ])
    if code != 0:
        return []
    history: List[FileChange] = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) == 4:
            history.append(FileChange(status="M", path=path, commit=fields[0],
                                      author=fields[1], date=fields[2], subject=fields[3]))
    return history


def recent_commits(root: str, limit: int = 15) -> List[FileChange]:
    """Recent commits on the current branch: the change feed the dashboard shows."""
    code, out = _git(root, [
        "log", f"-{limit}", "--date=short",
        "--pretty=format:%h%x09%an%x09%ad%x09%s",
    ])
    if code != 0:
        return []
    commits: List[FileChange] = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) == 4:
            commits.append(FileChange(status="M", path="", commit=fields[0], author=fields[1],
                                      date=fields[2], subject=fields[3]))
    return commits


def map_files_to_objects(cb: CodeBase, changes: List[FileChange]) -> Tuple[List[str], List[FileChange]]:
    """Map changed file paths back to object keys. Returns (keys, unmapped)."""
    index: Dict[str, str] = {}
    for obj in cb.objects.values():
        for p in obj.paths:
            index[_norm(p)] = obj.key

    keys: List[str] = []
    unmapped: List[FileChange] = []
    for change in changes:
        key = index.get(_norm(change.path))
        if key:
            if key not in keys:
                keys.append(key)
        else:
            unmapped.append(change)
    return keys, unmapped


def _norm(path: str) -> str:
    return os.path.normpath(path).replace("\\", "/").lower()


def _git(root: str, args: List[str]) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", root] + args,
            capture_output=True, text=True, timeout=60,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
