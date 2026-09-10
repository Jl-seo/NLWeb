"""
Object classification.

Two strategies, in priority order:

1. abapGit filename convention  ->  deterministic, no guessing.
     zcl_order.clas.abap            CLAS ZCL_ORDER
     zcl_order.clas.locals_imp.abap CLAS ZCL_ORDER  (same object, extra file)
     zif_order.intf.abap            INTF ZIF_ORDER
     zpp_report.prog.abap           PROG ZPP_REPORT
     zfg_order.fugr.abap            FUGR ZFG_ORDER
     zfg_order.fugr.zfm_create.abap FUNC ZFM_CREATE (belongs to FUGR ZFG_ORDER)
     zorder.tabl.xml                TABL ZORDER
     zi_order.ddls.asddls           DDLS ZI_ORDER

2. Header sniffing for loose SE38/SE80 dumps (.abap/.txt without the convention):
     REPORT / PROGRAM  -> PROG
     FUNCTION-POOL     -> FUGR
     FUNCTION x.       -> FUNC
     CLASS x DEFINITION-> CLAS
     INTERFACE x       -> INTF

BTP/CAP/Fiori files are classified by extension plus path/content markers.
"""

import os
import re
from typing import List, Optional, Tuple

from . import model as M

# ---------------------------------------------------------------- abapGit map

# abapGit writes <name>.<obj_type>.<ext>; obj_type is the lower-cased R3TR type.
ABAPGIT_TYPE_MAP = {
    "clas": M.CLASS,
    "intf": M.INTERFACE,
    "prog": M.PROGRAM,
    "fugr": M.FUNCTION_GROUP,
    "tabl": M.TABLE,
    "dtel": M.DATA_ELEMENT,
    "doma": M.DOMAIN,
    "view": M.VIEW,
    "ddls": M.CDS_VIEW,
    "ttyp": M.TABLE_TYPE,
    "msag": M.MESSAGE_CLASS,
    "tran": M.TRANSACTION,
    "enho": M.ENHANCEMENT,
    "sxci": M.BADI_DEFINITION,
    "shlp": M.SEARCH_HELP,
    "enqu": M.LOCK_OBJECT,
    "suso": M.AUTH_OBJECT,
    "ssfo": M.SMARTFORM,
    "idoc": M.IDOC_TYPE,
    "devc": M.PACKAGE,
    "bdef": M.BEHAVIOR_DEF,
    "srvd": M.SERVICE_DEF,
    "srvb": M.SERVICE_BINDING,
}

# abapGit escapes characters that are illegal in file names: #  ->  %23 etc.
_ESCAPES = {"%23": "#", "%2d": "-", "%2f": "/", "%3c": "<", "%3e": ">"}

ABAP_EXTS = {".abap", ".asddls", ".txt"}
XML_EXTS = {".xml"}
BTP_EXTS = {".cds", ".js", ".ts", ".mjs", ".json", ".xml"}

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "__pycache__", ".vscode",
    "coverage", ".idea", "target", ".fioritools",
}


def unescape(name: str) -> str:
    for enc, dec in _ESCAPES.items():
        name = name.replace(enc, dec)
    return name


def _parse_abapgit_name(filename: str, text: str = "") -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Returns (obj_type, object_name, member_name) or None if the file does not
    follow the abapGit convention.

    member_name is set for function modules (fugr.<fm>.abap), which abapGit
    stores as sub-files of their function group.

    UI5 files collide with this convention by accident -- Order.view.xml would
    parse as DDIC view "ORDER" -- so XML is only accepted when the abapGit
    marker is actually present in the file.
    """
    parts = filename.split(".")
    if len(parts) < 3:
        return None
    if filename.lower().endswith((".view.xml", ".fragment.xml", ".controller.js",
                                  ".controller.ts", ".view.js")):
        return None
    if filename.lower().endswith(".xml") and "<abapGit" not in text[:400]:
        return None
    name = unescape(parts[0]).upper()
    type_token = parts[1].lower()
    obj_type = ABAPGIT_TYPE_MAP.get(type_token)
    if not obj_type:
        return None

    # zfg_order.fugr.zfm_create.abap -> function module inside the group.
    if obj_type == M.FUNCTION_GROUP and len(parts) >= 4:
        middle = parts[2].lower()
        # `.locals_imp` / `.saplzfg` style helper files stay with the group.
        if not middle.startswith(("locals", "macros", "testclasses", "sapl", "top")):
            return (M.FUNCTION_MODULE, unescape(parts[2]).upper(), name)

    return (obj_type, name, None)


# ------------------------------------------------------------ header sniffing

_HEADER_PATTERNS = [
    (re.compile(r"^\s*(?:REPORT|PROGRAM)\s+([\w/]+)", re.I | re.M), M.PROGRAM),
    (re.compile(r"^\s*FUNCTION-POOL\s+([\w/]+)", re.I | re.M), M.FUNCTION_GROUP),
    (re.compile(r"^\s*FUNCTION\s+([\w/]+)\s*\.", re.I | re.M), M.FUNCTION_MODULE),
    (re.compile(r"^\s*CLASS\s+([\w/]+)\s+DEFINITION", re.I | re.M), M.CLASS),
    (re.compile(r"^\s*INTERFACE\s+([\w/]+)", re.I | re.M), M.INTERFACE),
    (re.compile(r"^\s*(?:@\w[\w.]*.*\s*)*define\s+(?:root\s+)?(?:abstract\s+)?view\s+(?:entity\s+)?([\w/]+)",
                re.I | re.M), M.CDS_VIEW),
]


def _sniff_header(text: str) -> Optional[Tuple[str, str]]:
    head = "\n".join(text.splitlines()[:80])
    for pattern, obj_type in _HEADER_PATTERNS:
        m = pattern.search(head)
        if m:
            return (obj_type, m.group(1).upper())
    return None


# ------------------------------------------------------------------- BTP/CAP

_CAP_SERVICE_RE = re.compile(r"^\s*(?:@[\w.():'\", ]+\s*)*service\s+([\w.]+)", re.M)
_UI5_CONTROLLER_RE = re.compile(r"controllerName\s*=\s*[\"']([\w.]+)[\"']")
_UI5_DEFINE_RE = re.compile(r"sap\.ui\.define\s*\(")


def classify_btp(path: str, text: str) -> Optional[Tuple[str, str]]:
    """Classify a BTP/CAP/Fiori file. Returns (obj_type, name) or None."""
    lower = path.replace("\\", "/").lower()
    base = os.path.basename(path)
    stem = base.split(".")[0]
    ext = os.path.splitext(base)[1].lower()

    if ext == ".cds":
        m = _CAP_SERVICE_RE.search(text)
        if m:
            return (M.CAP_SERVICE, m.group(1))
        return (M.CAP_ENTITY, _module_name(path))

    if base == "manifest.json":
        return (M.UI5_MANIFEST, _module_name(path))

    if ext in (".js", ".ts", ".mjs"):
        if "/srv/" in lower or lower.endswith(("-service.js", "-service.ts")):
            return (M.CAP_HANDLER, _module_name(path))
        if base.endswith((".controller.js", ".controller.ts")):
            return (M.UI5_CONTROLLER, _module_name(path))
        if _UI5_DEFINE_RE.search(text) or "/webapp/" in lower:
            return (M.UI5_MODULE, _module_name(path))
        return None

    if ext == ".xml":
        if base.endswith(".fragment.xml"):
            return (M.UI5_FRAGMENT, _module_name(path))
        if base.endswith(".view.xml") or "<mvc:View" in text or "<core:View" in text:
            return (M.UI5_VIEW, _module_name(path))
        return None

    return None


def _module_name(path: str) -> str:
    """
    Stable, human-recognisable name for a BTP artefact: the path below the
    nearest well-known root (webapp/, srv/, db/, app/), dots instead of slashes,
    matching how UI5 and CAP address modules.
    """
    norm = path.replace("\\", "/")
    for marker in ("/webapp/", "/srv/", "/db/", "/app/"):
        idx = norm.rfind(marker)
        if idx != -1:
            norm = norm[idx + 1:]
            break
    else:
        norm = os.path.basename(norm)
    for suffix in (".controller.js", ".controller.ts", ".fragment.xml", ".view.xml"):
        if norm.endswith(suffix):
            norm = norm[: -len(suffix)]
            break
    else:
        norm = os.path.splitext(norm)[0]
    if norm.startswith("webapp/"):
        # UI5 addresses modules by app namespace (orders.view.Order), never by
        # the physical 'webapp' folder; dropping it lets both sides meet.
        norm = norm[len("webapp/"):]
    return norm.replace("/", ".")


# ------------------------------------------------------------------ public API


def classify(path: str, text: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Classify one file.

    Returns (obj_type, object_name, parent_name) or None when the file is not a
    recognised SAP development object (README, .gitignore, package.json, ...).
    """
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()

    convention = _parse_abapgit_name(base, text)
    if convention:
        return convention

    if ext in (".abap", ".asddls") or (ext == ".txt" and _looks_like_abap(text)):
        sniffed = _sniff_header(text)
        if sniffed:
            return (sniffed[0], sniffed[1], None)
        return (M.INCLUDE, base.split(".")[0].upper(), None)

    if ext in BTP_EXTS:
        btp = classify_btp(path, text)
        if btp:
            return (btp[0], btp[1], None)

    return None


_ABAP_HINT_RE = re.compile(
    r"^\s*(REPORT|PROGRAM|FUNCTION|CLASS|INTERFACE|DATA|SELECT|FORM|METHOD|TYPES)\b",
    re.I | re.M,
)


def _looks_like_abap(text: str) -> bool:
    return bool(_ABAP_HINT_RE.search("\n".join(text.splitlines()[:60])))


def iter_source_files(root: str) -> List[str]:
    """Walk `root`, skipping VCS/build directories, returning candidate files."""
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in ABAP_EXTS | XML_EXTS | BTP_EXTS:
                found.append(os.path.join(dirpath, fn))
    return sorted(found)
