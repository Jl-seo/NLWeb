"""
Deterministic reference extraction for ABAP source.

ABAP statements are line-spanning and terminated by a period, so the source is
first normalised into logical statements (comments removed, continuation lines
joined). Every pattern below corresponds to a syntactic form that provably
creates a dependency, which is why the resulting graph can be trusted the way an
SE84 where-used list is trusted.

Dynamic calls (CALL FUNCTION lv_name, dynamic SELECT, CREATE OBJECT TYPE (lv))
cannot be resolved statically. They are not silently dropped: they are reported
as blind spots so a reviewer knows where the graph is incomplete.
"""

import re
from typing import List, NamedTuple, Optional, Sequence, Tuple

from . import model as M


class RawRef(NamedTuple):
    kind: str
    target_name: str
    candidate_types: Tuple[str, ...]
    line: int
    snippet: str


class Statement(NamedTuple):
    text: str
    line: int


# --------------------------------------------------------------- normalisation


def strip_comment(line: str) -> str:
    """Remove ABAP comments: '*' in column 1, and '"' outside a string literal."""
    if line[:1] == "*":
        return ""
    out = []
    in_str = False
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == quote:
                # '' inside a literal is an escaped quote, not the end.
                if quote == "'" and line[i + 1: i + 2] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_str = False
            out.append(ch)
        elif ch in ("'", "|"):
            in_str = True
            quote = ch
            out.append(ch)
        elif ch == '"':
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def logical_statements(text: str) -> List[Statement]:
    """Join continuation lines into period-terminated ABAP statements."""
    statements: List[Statement] = []
    buf: List[str] = []
    start_line = 1
    in_str = False
    quote = ""

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw)
        if not line.strip() and not buf:
            continue
        if not buf:
            start_line = lineno
        i = 0
        while i < len(line):
            ch = line[i]
            if in_str:
                if ch == quote:
                    if quote == "'" and line[i + 1: i + 2] == "'":
                        buf.append("''")
                        i += 2
                        continue
                    in_str = False
                buf.append(ch)
            elif ch in ("'", "|"):
                in_str = True
                quote = ch
                buf.append(ch)
            elif ch == ".":
                stmt = "".join(buf).strip()
                if stmt:
                    statements.append(Statement(re.sub(r"\s+", " ", stmt), start_line))
                buf = []
                start_line = lineno + 1
            else:
                buf.append(ch)
            i += 1
        buf.append(" ")

    tail = "".join(buf).strip()
    if tail:
        statements.append(Statement(re.sub(r"\s+", " ", tail), start_line))
    return statements


# ------------------------------------------------------------------- patterns

NAME = r"[/\w]+"          # ABAP names allow the /NAMESPACE/ form
LIT = r"'([/\w]+)'"

PATTERNS: Sequence[Tuple[re.Pattern, str, Tuple[str, ...]]] = [
    # --- procedural calls
    (re.compile(rf"\bCALL\s+FUNCTION\s+{LIT}", re.I), "CALL_FUNCTION", (M.FUNCTION_MODULE,)),
    (re.compile(rf"\bPERFORM\s+{NAME}\s+IN\s+PROGRAM\s+({NAME})", re.I), "PERFORM_EXT", (M.PROGRAM, M.INCLUDE)),
    (re.compile(rf"\bSUBMIT\s+({NAME})", re.I), "SUBMIT", (M.PROGRAM,)),
    (re.compile(rf"\bINCLUDE\s+({NAME})", re.I), "INCLUDE", (M.INCLUDE, M.PROGRAM)),
    (re.compile(rf"\bCALL\s+TRANSACTION\s+{LIT}", re.I), "CALL_TRANSACTION", (M.TRANSACTION,)),

    # --- OO
    (re.compile(rf"\bCLASS\s+{NAME}\s+DEFINITION\b.*?\bINHERITING\s+FROM\s+({NAME})", re.I), "INHERITS", (M.CLASS,)),
    (re.compile(rf"\bINTERFACES\s*:?\s*({NAME})", re.I), "IMPLEMENTS", (M.INTERFACE,)),
    (re.compile(rf"\bTYPE\s+REF\s+TO\s+({NAME})", re.I), "TYPE_REF", (M.CLASS, M.INTERFACE)),
    (re.compile(rf"\bCREATE\s+OBJECT\s+{NAME}\s+TYPE\s+({NAME})", re.I), "CREATE_OBJECT", (M.CLASS,)),
    (re.compile(rf"\bNEW\s+({NAME})\s*\(", re.I), "NEW", (M.CLASS,)),
    (re.compile(rf"\b({NAME})\s*=>", re.I), "STATIC_CALL", (M.CLASS, M.INTERFACE)),
    (re.compile(rf"\b({NAME})~", re.I), "INTERFACE_CALL", (M.INTERFACE, M.CLASS)),

    # --- data layer
    (re.compile(rf"\bSELECT\b.*?\bFROM\s+({NAME})", re.I), "SELECT", (M.TABLE, M.VIEW, M.CDS_VIEW)),
    (re.compile(rf"\bJOIN\s+({NAME})", re.I), "SELECT_JOIN", (M.TABLE, M.VIEW, M.CDS_VIEW)),
    (re.compile(rf"\b(?:INSERT|MODIFY)\s+({NAME})\s+FROM\b", re.I), "WRITE", (M.TABLE,)),
    (re.compile(rf"\bUPDATE\s+({NAME})\s+SET\b", re.I), "WRITE", (M.TABLE,)),
    (re.compile(rf"\bDELETE\s+FROM\s+({NAME})", re.I), "WRITE", (M.TABLE,)),
    (re.compile(rf"\bTABLES\s*:?\s*({NAME})", re.I), "TABLES", (M.TABLE, M.STRUCTURE)),
    (re.compile(rf"\b(?:TYPE|LIKE)\s+(?:STANDARD\s+TABLE\s+OF\s+|SORTED\s+TABLE\s+OF\s+|HASHED\s+TABLE\s+OF\s+|TABLE\s+OF\s+)?({NAME})(?:-{NAME})?",
                re.I), "TYPE_USE", (M.TABLE, M.STRUCTURE, M.DATA_ELEMENT, M.TABLE_TYPE, M.CDS_VIEW, M.VIEW)),

    # --- cross-cutting
    (re.compile(rf"\bMESSAGE\s+\w?\d{{3}}\(({NAME})\)", re.I), "MESSAGE", (M.MESSAGE_CLASS,)),
    (re.compile(rf"\bMESSAGE\s+ID\s+{LIT}", re.I), "MESSAGE", (M.MESSAGE_CLASS,)),
    (re.compile(rf"\bAUTHORITY-CHECK\s+OBJECT\s+{LIT}", re.I), "AUTH_CHECK", (M.AUTH_OBJECT,)),
    (re.compile(rf"\bGET\s+BADI\s+{NAME}\s+.*?\bTYPE\s+({NAME})", re.I), "GET_BADI", (M.BADI_DEFINITION,)),
    (re.compile(rf"\bFORMNAME\s*=\s*{LIT}", re.I), "SMARTFORM", (M.SMARTFORM,)),
    (re.compile(rf"\bENHANCEMENT-POINT\s+({NAME})", re.I), "ENHANCEMENT_POINT", (M.ENHANCEMENT,)),
]

# Statement forms that defeat static analysis; surfaced as blind spots.
DYNAMIC_PATTERNS: Sequence[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bCALL\s+FUNCTION\s+(?!')[\w<>-]+", re.I), "동적 펑션 호출 (CALL FUNCTION <변수>)"),
    (re.compile(r"\bCALL\s+METHOD\s*\(", re.I), "동적 메서드 호출 (CALL METHOD (변수))"),
    (re.compile(r"\bCREATE\s+OBJECT\s+[\w<>-]+\s+TYPE\s*\(", re.I), "동적 인스턴스 생성"),
    (re.compile(r"\bSELECT\b[^\.]*\bFROM\s*\(", re.I), "동적 테이블 SELECT"),
    (re.compile(r"\bSUBMIT\s*\(", re.I), "동적 프로그램 실행"),
    (re.compile(r"\bASSIGN\s+\(", re.I), "동적 필드 접근 (ASSIGN)"),
    (re.compile(r"\bcl_abap_typedescr|cl_abap_objectdescr", re.I), "RTTI 기반 동적 처리"),
]

# Statement forms that say something about the object itself, not its edges.
TAG_PATTERNS: Sequence[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bDESTINATION\b", re.I), "RFC"),
    (re.compile(r"\bIN\s+UPDATE\s+TASK\b", re.I), "UPDATE_TASK"),
    (re.compile(r"\bCOMMIT\s+WORK\b", re.I), "COMMIT_WORK"),
    (re.compile(r"\bAUTHORITY-CHECK\b", re.I), "AUTH_CHECK"),
    (re.compile(r"\bCALL\s+SCREEN\b|\bMODULE\s+\w+\s+OUTPUT\b", re.I), "DYNPRO"),
    (re.compile(r"\bEXPORT\b.*\bTO\s+(?:MEMORY|DATABASE)\b", re.I), "SHARED_STATE"),
    (re.compile(r"\bBAPI_\w+", re.I), "BAPI"),
    (re.compile(r"\bCLASS\s+\w+\s+DEFINITION\b.*\bFOR\s+TESTING\b", re.I), "TEST"),
]

# ABAP keywords that would otherwise be captured as type/class names.
STOPWORDS = {
    "TABLE", "STANDARD", "SORTED", "HASHED", "REF", "TO", "OF", "LINE", "BEGIN",
    "END", "STRING", "C", "I", "N", "P", "F", "X", "D", "T", "XSTRING", "ANY",
    "DATA", "ME", "SY", "CX_ROOT", "ABAP_BOOL", "ABAP_TRUE", "ABAP_FALSE",
    "SPACE", "INITIAL", "VALUE", "TYPE", "LIKE", "FROM", "INTO", "WHERE", "AND",
    "OR", "NOT", "IS", "IN", "WITH", "KEY", "SELECT", "ENDSELECT", "IF", "ELSE",
    "ENDIF", "LOOP", "ENDLOOP", "CASE", "WHEN", "ENDCASE", "DO", "ENDDO",
    "WHILE", "ENDWHILE", "TRY", "CATCH", "ENDTRY", "RAISE", "CHECK", "EXIT",
    "APPEND", "CLEAR", "REFRESH", "READ", "SORT", "COLLECT", "CONCATENATE",
    "MOVE", "CORRESPONDING", "SINGLE", "UP", "ROWS", "ORDER", "BY", "GROUP",
    "COUNT", "SUM", "MAX", "MIN", "AVG", "AS", "ON", "INNER", "LEFT", "OUTER",
    "FOR", "ALL", "ENTRIES", "TRANSPORTING", "ASSIGNING", "FIELD-SYMBOL",
    "PARAMETERS", "SELECT-OPTIONS", "CONSTANTS", "STATICS", "RETURNING",
    "EXPORTING", "IMPORTING", "CHANGING", "RECEIVING", "EXCEPTIONS", "OTHERS",
}


def _acceptable(name: str) -> bool:
    upper = name.upper()
    if upper in STOPWORDS or len(upper) < 3:
        return False
    if upper.isdigit():
        return False
    return True


def extract(text: str) -> Tuple[List[RawRef], List[str], List[Tuple[int, str]]]:
    """
    Returns (references, object_tags, blind_spots).

    blind_spots is a list of (line_number, human readable reason).
    """
    refs: List[RawRef] = []
    tags: List[str] = []
    blind: List[Tuple[int, str]] = []
    seen = set()

    for stmt in logical_statements(text):
        upper_free = stmt.text

        for pattern, kind, candidates in PATTERNS:
            for m in pattern.finditer(upper_free):
                target = (m.group(1) or "").upper()
                if not target or not _acceptable(target):
                    continue
                dedup = (kind, target, stmt.line)
                if dedup in seen:
                    continue
                seen.add(dedup)
                refs.append(RawRef(kind, target, candidates, stmt.line, stmt.text[:220]))

        for pattern, reason in DYNAMIC_PATTERNS:
            if pattern.search(upper_free):
                blind.append((stmt.line, reason))

        for pattern, tag in TAG_PATTERNS:
            if pattern.search(upper_free) and tag not in tags:
                tags.append(tag)

    return refs, tags, blind
