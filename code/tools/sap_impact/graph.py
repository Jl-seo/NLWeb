"""Traversal over the reference graph."""

from collections import defaultdict, deque
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from .model import CodeBase, Reference


class Hit(NamedTuple):
    key: str
    hops: int
    via: Tuple[str, ...]      # path from the changed object up to this one
    kinds: Tuple[str, ...]    # edge kinds along that path
    edge: Optional[Reference] # the edge that first reached this object


class Graph:
    def __init__(self, cb: CodeBase):
        self.cb = cb
        self.dependents: Dict[str, List[Reference]] = defaultdict(list)   # target -> edges into it
        self.dependencies: Dict[str, List[Reference]] = defaultdict(list) # source -> edges out of it
        for ref in cb.references:
            self.dependents[ref.target].append(ref)
            self.dependencies[ref.source].append(ref)

    # ------------------------------------------------------------- traversal

    def impacted_by(self, roots: Iterable[str], max_hops: int = 3) -> List[Hit]:
        """
        Reverse reachability: everything that would have to be re-tested if the
        given objects change. Breadth-first, so `hops` is the shortest distance
        and `via` the shortest path -- the one a reviewer should read first.
        """
        roots = [r for r in roots]
        seen: Set[str] = set(roots)
        queue: deque = deque((r, 0, (r,), ()) for r in roots)
        hits: List[Hit] = []

        while queue:
            key, hops, path, kinds = queue.popleft()
            if hops >= max_hops:
                continue
            for ref in self.dependents.get(key, []):
                if ref.source in seen:
                    continue
                seen.add(ref.source)
                new_path = path + (ref.source,)
                new_kinds = kinds + (ref.kind,)
                hits.append(Hit(ref.source, hops + 1, new_path, new_kinds, ref))
                queue.append((ref.source, hops + 1, new_path, new_kinds))

        hits.sort(key=lambda h: (h.hops, h.key))
        return hits

    def depends_on(self, roots: Iterable[str], max_hops: int = 2) -> List[Hit]:
        """Forward reachability: what the changed object itself relies on."""
        seen: Set[str] = set(roots)
        queue: deque = deque((r, 0, (r,), ()) for r in roots)
        hits: List[Hit] = []
        while queue:
            key, hops, path, kinds = queue.popleft()
            if hops >= max_hops:
                continue
            for ref in self.dependencies.get(key, []):
                if ref.target in seen:
                    continue
                seen.add(ref.target)
                hits.append(Hit(ref.target, hops + 1, path + (ref.target,), kinds + (ref.kind,), ref))
                queue.append((ref.target, hops + 1, path + (ref.target,), kinds + (ref.kind,)))
        hits.sort(key=lambda h: (h.hops, h.key))
        return hits

    # ----------------------------------------------------------------- stats

    def fan_in(self, key: str) -> int:
        return len({r.source for r in self.dependents.get(key, [])})

    def fan_out(self, key: str) -> int:
        return len({r.target for r in self.dependencies.get(key, [])})

    def hotspots(self, limit: int = 15) -> List[Tuple[str, int]]:
        counts = [(key, self.fan_in(key)) for key in self.cb.objects]
        counts.sort(key=lambda x: (-x[1], x[0]))
        return [c for c in counts[:limit] if c[1] > 0]
