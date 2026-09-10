"""
Emit the OpenAPI schema for the Foundry OpenAPI tool.

FastAPI produces OpenAPI 3.1. Foundry's tool documentation calls for 3.0+, and
3.1's nullable form (`"type": ["string", "null"]`) is not valid 3.0, so the
schema is downgraded here rather than hand-maintained: one generator, no drift
between the running service and the schema pasted into Foundry.

    python -m tools.sap_impact.service.export_openapi --url https://<app>.azurewebsites.net \
        --api-key-header > openapi.json
"""

import argparse
import copy
import json
import os
import sys
from typing import Any, Dict

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "sap_impact.service"


def downgrade_to_30(node: Any) -> Any:
    """Convert 3.1-only constructs into their 3.0 equivalents, in place-ish."""
    if isinstance(node, list):
        return [downgrade_to_30(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: Dict[str, Any] = {}
    for key, value in node.items():
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
            if "null" in value:
                out["nullable"] = True
            continue
        if key == "anyOf" and isinstance(value, list):
            variants = [v for v in value if not (isinstance(v, dict) and v.get("type") == "null")]
            if len(variants) == 1 and len(variants) != len(value):
                # Optional[X] -> X + nullable, which is how 3.0 spells it.
                merged = downgrade_to_30(variants[0])
                if isinstance(merged, dict):
                    merged = dict(merged)
                    merged["nullable"] = True
                    out.update(merged)
                    continue
            out["anyOf"] = downgrade_to_30(variants or value)
            continue
        if key == "examples" and isinstance(value, list):
            if value:
                out["example"] = downgrade_to_30(value[0])
            continue
        if key == "const":
            out["enum"] = [value]
            continue
        out[key] = downgrade_to_30(value)
    return out


def build(server_url: str, api_key_header: bool) -> Dict[str, Any]:
    os.environ.setdefault("SAP_IMPACT_PUBLIC_URL", server_url)
    from .app import app  # imported after the env var so the server URL is picked up

    spec = copy.deepcopy(app.openapi())
    spec["openapi"] = "3.0.3"
    spec["servers"] = [{"url": server_url}]
    spec = downgrade_to_30(spec)

    if api_key_header:
        # Foundry stores the key in a 'custom keys' connection and sends it on
        # every call, so the parameter must not appear in the operations.
        spec.setdefault("components", {})["securitySchemes"] = {
            "apiKeyHeader": {"type": "apiKey", "name": "x-api-key", "in": "header"}
        }
        spec["security"] = [{"apiKeyHeader": []}]

    _assert_operation_ids(spec)
    return spec


def _assert_operation_ids(spec: Dict[str, Any]) -> None:
    """Foundry requires an operationId of letters, '-' and '_' on every operation."""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_")
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            op_id = operation.get("operationId", "")
            if not op_id:
                raise SystemExit(f"operationId 누락: {method.upper()} {path}")
            bad = set(op_id) - allowed
            if bad:
                raise SystemExit(f"operationId '{op_id}' 에 허용되지 않는 문자: {''.join(sorted(bad))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Foundry OpenAPI 도구용 스키마 출력")
    parser.add_argument("--url", required=True, help="배포된 서비스의 공개 URL (https://...)")
    parser.add_argument("--api-key-header", action="store_true",
                        help="x-api-key 보안 스키마 포함 (Foundry custom keys 연결용)")
    parser.add_argument("--out", help="파일로 저장 (생략 시 stdout)")
    args = parser.parse_args()

    spec = build(args.url, args.api_key_header)
    text = json.dumps(spec, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"저장: {args.out}  (operation {sum(1 for p in spec['paths'].values() for _ in p)}건)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
