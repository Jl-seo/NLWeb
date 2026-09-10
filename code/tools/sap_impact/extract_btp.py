"""
Reference extraction for SAP BTP artefacts: ABAP CDS (.asddls), CAP CDS (.cds),
CAP service handlers (JS/TS), and Fiori/UI5 (controllers, views, fragments,
manifest.json).

Same contract as extract_abap.extract: return raw references plus tags, so the
graph builder does not care which technology an object came from. That is what
lets one impact query cross the ABAP -> CDS -> OData -> UI5 boundary, which is
exactly where hand-made impact analysis usually breaks down.
"""

import json
import os
import re
from typing import List, Tuple

from . import model as M
from .extract_abap import RawRef

# ------------------------------------------------------------------- ABAP CDS

_CDS_SELECT_FROM = re.compile(r"\b(?:select\s+(?:distinct\s+)?from|projection\s+on)\s+([\w./]+)", re.I)
_CDS_JOIN = re.compile(r"\bjoin\s+([\w./]+)", re.I)
_CDS_ASSOC = re.compile(r"\b(?:association(?:\s*\[[^\]]*\])?\s+to(?:\s+parent)?|composition(?:\s*\[[^\]]*\])?\s+of)\s+([\w./]+)", re.I)
_CDS_SQLVIEW = re.compile(r"@AbapCatalog\.sqlViewName\s*:\s*'([\w/]+)'", re.I)
_CDS_USING = re.compile(r"^\s*using\s+(?:\{[^}]*\}\s+from\s+)?['\"]?([\w./{}, ]+?)['\"]?\s*;", re.I | re.M)
_CDS_EXTEND = re.compile(r"\bextend\s+(?:entity\s+|service\s+)?([\w.]+)", re.I)
_CDS_TYPE = re.compile(r":\s*(?:type\s+of\s+)?([A-Za-z_][\w.]*)\s*(?:;|,|\))", re.I)


def extract_cds(text: str, is_abap_cds: bool = True) -> Tuple[List[RawRef], List[str]]:
    refs: List[RawRef] = []
    tags: List[str] = []
    base_types = (M.TABLE, M.VIEW, M.CDS_VIEW) if is_abap_cds else (M.CAP_ENTITY, M.CAP_SERVICE)

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.split("//")[0]
        for pattern, kind in (
            (_CDS_SELECT_FROM, "CDS_FROM"),
            (_CDS_JOIN, "CDS_JOIN"),
            (_CDS_ASSOC, "CDS_ASSOCIATION"),
            (_CDS_EXTEND, "CDS_EXTEND"),
        ):
            for m in pattern.finditer(stripped):
                target = m.group(1).strip()
                if target and not target.lower().startswith(("select", "from")):
                    refs.append(RawRef(kind, _norm(target, is_abap_cds), base_types,
                                       lineno, stripped.strip()[:220]))
        for m in _CDS_USING.finditer(stripped):
            for token in m.group(1).replace("{", "").replace("}", "").split(","):
                token = token.strip()
                if token:
                    refs.append(RawRef("CDS_USING", _norm(token, is_abap_cds),
                                       (M.CAP_ENTITY, M.CAP_SERVICE), lineno, stripped.strip()[:220]))
        if _CDS_SQLVIEW.search(stripped):
            tags.append("SQL_VIEW")

    if re.search(r"@ObjectModel\.\w*[Cc]reate|@Metadata\.allowExtensions", text):
        tags.append("EXTENSIBLE")
    if re.search(r"\bdefine\s+root\s+view", text, re.I):
        tags.append("ROOT_VIEW")
    if re.search(r"@OData\.publish\s*:\s*true", text, re.I):
        tags.append("ODATA_PUBLISHED")
    return refs, tags


def _norm(name: str, is_abap_cds: bool) -> str:
    name = name.strip().strip("'\";")
    # './db/schema' -> db.schema ; keeps CAP module identity comparable to classifier names
    if name.startswith("."):
        name = name.lstrip("./")
        name = name.replace("/", ".")
    return name.upper() if is_abap_cds else name


# ---------------------------------------------------------------- CAP JS / TS

_JS_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_JS_IMPORT = re.compile(r"""^\s*import\s+(?:[\w*{},\s]+\s+from\s+)?['"]([^'"]+)['"]""", re.M)
_JS_CDS_ENTITIES = re.compile(r"""cds\.entities\(\s*['"]([^'"]+)['"]""")
_JS_SRV_ON = re.compile(r"""\bsrv\.(?:on|before|after)\s*\(\s*['"][^'"]+['"]\s*,\s*['"]([^'"]+)['"]""")
_JS_UI5_DEFINE = re.compile(r"sap\.ui\.define\s*\(\s*\[([^\]]*)\]", re.S)
_JS_FRAGMENT_LOAD = re.compile(r"""name\s*:\s*['"]([\w.]+)['"]""")
_JS_NAV_TO = re.compile(r"""navTo\(\s*['"]([\w.]+)['"]""")


def extract_js(text: str, path: str) -> Tuple[List[RawRef], List[str]]:
    refs: List[RawRef] = []
    tags: List[str] = []

    for pattern, kind, candidates in (
        (_JS_REQUIRE, "JS_REQUIRE", (M.CAP_HANDLER, M.CAP_ENTITY, M.UI5_MODULE)),
        (_JS_IMPORT, "JS_IMPORT", (M.CAP_HANDLER, M.CAP_ENTITY, M.UI5_MODULE)),
        (_JS_CDS_ENTITIES, "CAP_ENTITY_USE", (M.CAP_ENTITY, M.CAP_SERVICE)),
        (_JS_SRV_ON, "CAP_HANDLER_BIND", (M.CAP_ENTITY,)),
        (_JS_FRAGMENT_LOAD, "UI5_FRAGMENT_USE", (M.UI5_FRAGMENT, M.UI5_VIEW)),
        (_JS_NAV_TO, "UI5_NAV", (M.UI5_VIEW,)),
    ):
        for m in pattern.finditer(text):
            target = m.group(1).strip()
            if not target or target.startswith(("@sap/", "@cap-js/")) or _is_npm(target):
                continue
            refs.append(RawRef(kind, _js_module_name(target), candidates,
                               _line_of(text, m.start()), _snippet(text, m.start())))

    for m in _JS_UI5_DEFINE.finditer(text):
        for token in re.findall(r"""['"]([^'"]+)['"]""", m.group(1)):
            if token.startswith("sap/"):
                continue
            refs.append(RawRef("UI5_DEPENDENCY", token.replace("/", "."),
                               (M.UI5_MODULE, M.UI5_CONTROLLER), _line_of(text, m.start()),
                               "sap.ui.define([...])"))

    if "@sap/cds" in text or "cds.serve" in text:
        tags.append("CAP_RUNTIME")
    if re.search(r"\bSELECT\.from|INSERT\.into|UPDATE\(|DELETE\.from", text):
        tags.append("CQN_QUERY")
    if re.search(r"\bcds\.connect\.to\(", text):
        tags.append("REMOTE_SERVICE")
    return refs, tags


def _is_npm(spec: str) -> bool:
    """node_modules import (bare specifier) rather than a project-local module."""
    return not spec.startswith((".", "/"))


def _js_module_name(spec: str) -> str:
    spec = spec.strip()
    if spec.startswith("."):
        spec = spec.lstrip("./")
    for suffix in (".js", ".ts", ".cds", ".json"):
        if spec.endswith(suffix):
            spec = spec[: -len(suffix)]
    return spec.replace("/", ".")


# ------------------------------------------------------------------- UI5 XML

_XML_CONTROLLER = re.compile(r"""controllerName\s*=\s*['"]([\w.]+)['"]""")
_XML_FRAGMENT = re.compile(r"""fragmentName\s*=\s*['"]([\w.]+)['"]""")
_XML_VIEWNAME = re.compile(r"""viewName\s*=\s*['"]([\w.]+)['"]""")
_XML_CUSTOM_NS = re.compile(r"""xmlns:(\w+)\s*=\s*['"]([\w.]+)['"]""")
_XML_BINDING = re.compile(r"""(?:path|items)\s*=\s*['"]\{[^'"]*?/(\w+)[^'"]*?\}['"]""")


def extract_ui5_xml(text: str) -> Tuple[List[RawRef], List[str]]:
    refs: List[RawRef] = []
    tags: List[str] = []
    for pattern, kind, candidates in (
        (_XML_CONTROLLER, "UI5_CONTROLLER_BIND", (M.UI5_CONTROLLER,)),
        (_XML_FRAGMENT, "UI5_FRAGMENT_USE", (M.UI5_FRAGMENT,)),
        (_XML_VIEWNAME, "UI5_VIEW_USE", (M.UI5_VIEW,)),
    ):
        for m in pattern.finditer(text):
            refs.append(RawRef(kind, m.group(1), candidates,
                               _line_of(text, m.start()), _snippet(text, m.start())))
    for m in _XML_CUSTOM_NS.finditer(text):
        ns = m.group(2)
        if not ns.startswith("sap."):
            refs.append(RawRef("UI5_CUSTOM_CONTROL", ns, (M.UI5_MODULE,),
                               _line_of(text, m.start()), _snippet(text, m.start())))
    if "smartTable" in text or "smartfilterbar" in text.lower():
        tags.append("SMART_CONTROL")
    return refs, tags


# --------------------------------------------------------------- manifest.json


def extract_manifest(text: str) -> Tuple[List[RawRef], List[str]]:
    refs: List[RawRef] = []
    tags: List[str] = []
    try:
        data = json.loads(text)
    except ValueError:
        return refs, ["MANIFEST_UNPARSEABLE"]

    app = data.get("sap.app", {})
    for ds_name, ds in (app.get("dataSources") or {}).items():
        uri = ds.get("uri", "")
        refs.append(RawRef("ODATA_SOURCE", uri or ds_name,
                           (M.SERVICE_BINDING, M.CAP_SERVICE), 1, f"dataSource {ds_name}: {uri}"))
        tags.append("ODATA_CONSUMER")

    ui5 = data.get("sap.ui5", {})
    routing = ui5.get("routing", {}) or {}
    for target in (routing.get("targets") or {}).values():
        view = target.get("viewName") or target.get("name")
        if view:
            refs.append(RawRef("UI5_ROUTE_TARGET", view, (M.UI5_VIEW,), 1, f"route target {view}"))
    return refs, tags


# ---------------------------------------------------------- abapGit XML metadata

_XML_TEXT_FIELDS = ("DDTEXT", "STEXT", "TTEXT", "DESCRIPT", "TEXT", "DESCRIPTION")
_XML_TAG = "<{0}>(.*?)</{0}>"


def extract_abapgit_xml(text: str) -> Tuple[List[RawRef], List[str], str]:
    """Pull description, package and a few metadata edges out of abapGit XML."""
    refs: List[RawRef] = []
    tags: List[str] = []
    description = ""

    for field in _XML_TEXT_FIELDS:
        m = re.search(_XML_TAG.format(field), text, re.S)
        if m and m.group(1).strip():
            description = re.sub(r"\s+", " ", m.group(1)).strip()
            break

    # Transaction -> program it starts.
    m = re.search(_XML_TAG.format("PGMNA"), text)
    if m and m.group(1).strip():
        refs.append(RawRef("TRANSACTION_PROGRAM", m.group(1).strip().upper(),
                           (M.PROGRAM,), 1, "TRAN -> PROG"))
    # Table field types point at data elements / domains.
    for m in re.finditer(_XML_TAG.format("ROLLNAME"), text):
        name = m.group(1).strip().upper()
        if name:
            refs.append(RawRef("FIELD_TYPE", name, (M.DATA_ELEMENT, M.STRUCTURE, M.TABLE),
                               1, f"ROLLNAME {name}"))
    for m in re.finditer(_XML_TAG.format("DOMNAME"), text):
        name = m.group(1).strip().upper()
        if name:
            refs.append(RawRef("DOMAIN_USE", name, (M.DOMAIN,), 1, f"DOMNAME {name}"))
    # Delivery class / table category hints.
    if re.search(_XML_TAG.format("CONTFLAG"), text):
        tags.append("DELIVERY_CLASS_SET")
    return refs, tags, description


# ------------------------------------------------------------------- helpers


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _snippet(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:220]
