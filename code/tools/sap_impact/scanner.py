"""
Directory scan: SAP source tree -> object catalogue + reference graph.

This is the deterministic half of the tool. No LLM is involved here, so the same
directory always produces the same graph, and every edge carries the file, line
and source statement that produced it.
"""

import os
from typing import Dict, List, Optional, Tuple

from . import classifier, extract_abap, extract_btp
from . import model as M
from .model import CodeBase, Reference, SapObject

MAX_FILE_BYTES = 4 * 1024 * 1024


def scan(root: str, verbose: bool = False) -> CodeBase:
    root = os.path.abspath(root)
    cb = CodeBase(root=root)
    pending: List[Tuple[SapObject, List[extract_abap.RawRef]]] = []

    for path in classifier.iter_source_files(root):
        rel = os.path.relpath(path, root)
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                cb.skipped_files.append(f"{rel} (too large)")
                continue
            text = _read(path)
        except OSError as exc:
            cb.skipped_files.append(f"{rel} ({exc})")
            continue

        classified = classifier.classify(path, text)
        if not classified:
            continue
        obj_type, name, parent = classified

        obj = SapObject(
            name=name,
            obj_type=obj_type,
            paths=[rel],
            loc=text.count("\n") + 1,
        )

        refs, tags, blind = _extract(obj_type, path, text)
        obj.tags.update(tags)

        if obj_type in (M.TABLE, M.DATA_ELEMENT, M.DOMAIN, M.TRANSACTION, M.MESSAGE_CLASS,
                        M.TABLE_TYPE, M.LOCK_OBJECT, M.SEARCH_HELP, M.VIEW) or path.endswith(".xml"):
            xml_refs, xml_tags, desc = extract_btp.extract_abapgit_xml(text)
            refs = refs + xml_refs
            obj.tags.update(xml_tags)
            obj.description = obj.description or (desc or None)

        stored = cb.add_object(obj)

        # A function module belongs to its function group: changing the group
        # (its TOP include, global data) reaches every module inside it.
        if parent:
            group = cb.add_object(SapObject(name=parent, obj_type=M.FUNCTION_GROUP, paths=[]))
            refs = list(refs) + [extract_abap.RawRef(
                "BELONGS_TO", group.name, (M.FUNCTION_GROUP,), 1, f"FUGR {group.name}")]

        if blind:
            cb.blind_spots.setdefault(stored.key, []).extend(
                {"line": ln, "reason": reason, "file": rel} for ln, reason in blind
            )
        pending.append((stored, list(refs)))
        if verbose:
            print(f"  {stored.key:<40} {len(refs):>4} refs  {rel}")

    _resolve(cb, pending)
    return cb


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _extract(obj_type: str, path: str, text: str):
    """Route a file to the right extractor based on its classified type."""
    ext = os.path.splitext(path)[1].lower()

    if obj_type == M.CDS_VIEW:
        refs, tags = extract_btp.extract_cds(text, is_abap_cds=True)
        return refs, tags, []
    if obj_type in (M.CAP_ENTITY, M.CAP_SERVICE) and ext == ".cds":
        refs, tags = extract_btp.extract_cds(text, is_abap_cds=False)
        return refs, tags, []
    if obj_type in (M.CAP_HANDLER, M.UI5_CONTROLLER, M.UI5_MODULE):
        refs, tags = extract_btp.extract_js(text, path)
        return refs, tags, []
    if obj_type in (M.UI5_VIEW, M.UI5_FRAGMENT):
        refs, tags = extract_btp.extract_ui5_xml(text)
        return refs, tags, []
    if obj_type == M.UI5_MANIFEST:
        refs, tags = extract_btp.extract_manifest(text)
        return refs, tags, []
    if ext in (".abap", ".txt"):
        return extract_abap.extract(text)
    return [], [], []


# ----------------------------------------------------------------- resolution


def _resolve(cb: CodeBase, pending) -> None:
    """
    Turn (name, candidate types) into concrete object keys.

    Preference order: an object whose type is one of the candidate types, then
    any object with that name. Anything left over is recorded as unresolved --
    typically a standard SAP object (CL_*, MARA, BAPI_*) or an npm package,
    which is information in itself.
    """
    by_name: Dict[str, List[SapObject]] = {}
    by_suffix: Dict[str, List[SapObject]] = {}
    for obj in cb.objects.values():
        by_name.setdefault(obj.name.upper(), []).append(obj)
        suffix = _suffix(obj.name)
        if suffix:
            by_suffix.setdefault(suffix, []).append(obj)

    seen_edges = set()
    for source, refs in pending:
        for raw in refs:
            target_obj = _lookup(by_name, raw.target_name, raw.candidate_types)
            if target_obj is None:
                # UI5/CAP modules are addressed by app namespace (orders.view.Order)
                # while the file lives at view/Order.view.xml. Match on the last two
                # dotted segments, which is the part both spellings share.
                target_obj = _lookup(by_suffix, _suffix(raw.target_name), raw.candidate_types)
            if target_obj is None and raw.kind == "ODATA_SOURCE":
                # A manifest points at a URI (/odata/v4/OrderService/), not a name.
                # Match its path segments against service objects so the UI5 app
                # connects to the service that actually serves it.
                for segment in reversed([s for s in raw.target_name.split("/") if s]):
                    target_obj = _lookup(by_name, segment, raw.candidate_types)
                    if target_obj is not None:
                        break
            if target_obj is None:
                if _is_custom(raw.target_name):
                    cb.unresolved.append(Reference(
                        source=source.key, target=raw.target_name, kind=raw.kind,
                        line=raw.line, snippet=raw.snippet))
                continue
            if target_obj.key == source.key:
                continue
            edge = (source.key, target_obj.key, raw.kind)
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            cb.references.append(Reference(
                source=source.key, target=target_obj.key, kind=raw.kind,
                line=raw.line, snippet=raw.snippet))


def _suffix(name: str) -> str:
    """Last two dotted segments of a module name, upper-cased for comparison."""
    parts = [p for p in name.split(".") if p]
    if len(parts) < 2:
        return ""
    return ".".join(parts[-2:]).upper()


def _lookup(by_name, name: str, candidates) -> Optional[SapObject]:
    if not name:
        return None
    hits = by_name.get(name.upper())
    if not hits:
        return None
    for cand in candidates:
        for obj in hits:
            if obj.obj_type == cand:
                return obj
    return hits[0]


def _is_custom(name: str) -> bool:
    """Customer namespace: Z*, Y*, /NAMESPACE/*. Standard SAP objects are noise here."""
    upper = name.upper()
    return upper.startswith(("Z", "Y")) or upper.startswith("/")
