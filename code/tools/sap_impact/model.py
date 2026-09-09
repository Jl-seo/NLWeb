"""
Core data model for SAP change-impact analysis.

An SAP code base is represented as a graph:
  - nodes: SapObject (an ABAP class, report, function module, DDIC table, CDS view,
           CAP service, UI5 controller, ...)
  - edges: Reference (source object uses target object, with the syntax that proved it)

Every edge is produced by a deterministic extractor, never by an LLM, so that the
"what is affected" answer is reproducible and auditable. The LLM layer only reads
this graph and explains it.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set


# Object types. Kept as plain strings (not an Enum) so that unknown SAP object
# types coming from newer abapGit versions degrade gracefully instead of raising.
CLASS = "CLAS"
INTERFACE = "INTF"
PROGRAM = "PROG"
INCLUDE = "INCL"
FUNCTION_GROUP = "FUGR"
FUNCTION_MODULE = "FUNC"
TABLE = "TABL"
STRUCTURE = "STRU"
DATA_ELEMENT = "DTEL"
DOMAIN = "DOMA"
VIEW = "VIEW"
CDS_VIEW = "DDLS"
TABLE_TYPE = "TTYP"
MESSAGE_CLASS = "MSAG"
TRANSACTION = "TRAN"
ENHANCEMENT = "ENHO"
BADI_DEFINITION = "SXCI"
SEARCH_HELP = "SHLP"
LOCK_OBJECT = "ENQU"
AUTH_OBJECT = "SUSO"
SMARTFORM = "SSFO"
IDOC_TYPE = "IDOC"
PACKAGE = "DEVC"
BEHAVIOR_DEF = "BDEF"
SERVICE_DEF = "SRVD"
SERVICE_BINDING = "SRVB"

# BTP / CAP / Fiori
CAP_SERVICE = "CAP_SRV"
CAP_ENTITY = "CAP_ENTITY"
CAP_HANDLER = "CAP_HANDLER"
UI5_CONTROLLER = "UI5_CTRL"
UI5_VIEW = "UI5_VIEW"
UI5_FRAGMENT = "UI5_FRAG"
UI5_MODULE = "UI5_MOD"
UI5_MANIFEST = "UI5_MANIFEST"

UNKNOWN = "UNKNOWN"

# Object types that represent an externally visible contract. A change reaching
# one of these is a release-risk event, not just an internal refactor.
EXTERNAL_CONTRACT_TYPES = {
    FUNCTION_MODULE,   # may be RFC-enabled
    TRANSACTION,
    IDOC_TYPE,
    SERVICE_BINDING,
    SERVICE_DEF,
    CAP_SERVICE,
    # UI5 views are user-facing but not a contract with another system: keeping
    # them here made every formatter tweak look like an interface change.
}

# Object types whose change forces a data-layer conversion / downtime consideration.
DATA_LAYER_TYPES = {TABLE, STRUCTURE, DATA_ELEMENT, DOMAIN, TABLE_TYPE, LOCK_OBJECT}

TYPE_LABELS = {
    CLASS: "ABAP 클래스",
    INTERFACE: "ABAP 인터페이스",
    PROGRAM: "ABAP 프로그램/리포트",
    INCLUDE: "인클루드",
    FUNCTION_GROUP: "펑션 그룹",
    FUNCTION_MODULE: "펑션 모듈",
    TABLE: "DDIC 테이블",
    STRUCTURE: "DDIC 구조",
    DATA_ELEMENT: "데이터 엘리먼트",
    DOMAIN: "도메인",
    VIEW: "DDIC 뷰",
    CDS_VIEW: "CDS 뷰",
    TABLE_TYPE: "테이블 타입",
    MESSAGE_CLASS: "메시지 클래스",
    TRANSACTION: "트랜잭션 코드",
    ENHANCEMENT: "인핸스먼트",
    BADI_DEFINITION: "BAdI 정의",
    SEARCH_HELP: "서치 헬프",
    LOCK_OBJECT: "락 오브젝트",
    AUTH_OBJECT: "권한 오브젝트",
    SMARTFORM: "스마트폼",
    IDOC_TYPE: "IDoc 타입",
    PACKAGE: "패키지",
    BEHAVIOR_DEF: "비헤이비어 정의",
    SERVICE_DEF: "서비스 정의",
    SERVICE_BINDING: "서비스 바인딩",
    CAP_SERVICE: "CAP 서비스",
    CAP_ENTITY: "CAP 엔티티",
    CAP_HANDLER: "CAP 핸들러(JS/TS)",
    UI5_CONTROLLER: "UI5 컨트롤러",
    UI5_VIEW: "UI5 뷰",
    UI5_FRAGMENT: "UI5 프래그먼트",
    UI5_MODULE: "UI5 모듈",
    UI5_MANIFEST: "UI5 매니페스트",
    UNKNOWN: "미분류",
}


def type_label(obj_type: str) -> str:
    return TYPE_LABELS.get(obj_type, obj_type)


@dataclass
class Reference:
    """A directed edge: `source` depends on `target`."""

    source: str          # object key, e.g. "CLAS/ZCL_ORDER"
    target: str          # object key
    kind: str            # CALL_FUNCTION, SELECT, TYPE_REF, INHERITS, ...
    line: int            # 1-based line number in the source file
    snippet: str         # the matched source line, trimmed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SapObject:
    """A single SAP development object discovered on disk."""

    name: str                       # ZCL_ORDER (upper case for ABAP, path-ish for BTP)
    obj_type: str                   # CLAS, PROG, ...
    paths: List[str] = field(default_factory=list)   # every file contributing to it
    package: Optional[str] = None
    description: Optional[str] = None
    loc: int = 0                    # lines of code across all paths
    tags: Set[str] = field(default_factory=set)      # RFC, UPDATE_TASK, BADI_IMPL, ...

    @property
    def key(self) -> str:
        return f"{self.obj_type}/{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tags"] = sorted(self.tags)
        d["key"] = self.key
        return d


@dataclass
class CodeBase:
    """Scan result: the object catalogue plus the reference graph."""

    root: str
    objects: Dict[str, SapObject] = field(default_factory=dict)
    references: List[Reference] = field(default_factory=list)
    unresolved: List[Reference] = field(default_factory=list)  # target not in this code base
    skipped_files: List[str] = field(default_factory=list)
    # object key -> [{"line": int, "reason": str}]: places where static analysis
    # provably cannot see the dependency (dynamic calls, RTTI, generated names).
    blind_spots: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    def add_object(self, obj: SapObject) -> SapObject:
        existing = self.objects.get(obj.key)
        if existing:
            existing.paths.extend(p for p in obj.paths if p not in existing.paths)
            existing.loc += obj.loc
            existing.tags |= obj.tags
            existing.package = existing.package or obj.package
            existing.description = existing.description or obj.description
            return existing
        self.objects[obj.key] = obj
        return obj

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeBase":
        cb = cls(root=data.get("root", ""))
        for raw in data.get("objects", []):
            obj = SapObject(
                name=raw["name"], obj_type=raw["obj_type"], paths=list(raw.get("paths", [])),
                package=raw.get("package"), description=raw.get("description"),
                loc=raw.get("loc", 0), tags=set(raw.get("tags", [])),
            )
            cb.objects[obj.key] = obj
        cb.references = [Reference(**r) for r in data.get("references", [])]
        cb.unresolved = [Reference(**r) for r in data.get("unresolved", [])]
        cb.skipped_files = list(data.get("skipped_files", []))
        cb.blind_spots = dict(data.get("blind_spots", {}))
        return cb

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "objects": [o.to_dict() for o in self.objects.values()],
            "references": [r.to_dict() for r in self.references],
            "unresolved": [r.to_dict() for r in self.unresolved],
            "skipped_files": self.skipped_files,
            "blind_spots": self.blind_spots,
        }
