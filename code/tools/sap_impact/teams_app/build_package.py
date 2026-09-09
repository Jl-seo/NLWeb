"""
Build the Teams app package (.zip) from the manifest template.

Kept as a script rather than a checked-in manifest because the values that
change per tenant and per environment -- app id, host, bot id -- must not be
baked into source control, and a half-substituted manifest fails validation only
after upload, which is a slow way to find a typo.

    python build_package.py --host sap-impact.azurewebsites.net \
        --app-id 11111111-2222-3333-4444-555555555555 \
        --developer "Contoso IT" [--bot-id <Azure Bot app id>] [--sso-client-id <Entra app id>]

Produces sap-impact-teams-app.zip: sideload it in Teams (Apps > Manage your apps
> Upload an app) or submit it to the org catalog.
"""

import argparse
import json
import os
import re
import sys
import zipfile
from typing import Any, Dict

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "manifest.template.json")
ICONS = ("color.png", "outline.png")
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def substitute(text: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("${{" + key + "}}", value)
    return text


def add_bot(manifest: Dict[str, Any], bot_id: str, host: str) -> None:
    """
    The bot powers the chat entry point: an Adaptive Card summary in a chat or
    channel, plus link unfurling so pasting a transport or PR link produces the
    same card. Its messaging endpoint must call POST /cards/impact.
    """
    manifest["bots"] = [{
        "botId": bot_id,
        "scopes": ["personal", "team", "groupChat"],
        "supportsFiles": False,
        "isNotificationOnly": False,
        "commandLists": [{
            "scopes": ["personal", "team", "groupChat"],
            "commands": [
                {"title": "영향", "description": "오브젝트 변경 영향 (예: 영향 ZORDER_HDR)"},
                {"title": "질문", "description": "업무 용어로 질문 (예: 질문 구매요청 승인 로직)"},
                {"title": "전송분", "description": "git 범위의 수정내역 영향 (예: 전송분 main..release)"},
            ],
        }],
    }]
    manifest["composeExtensions"] = [{
        "botId": bot_id,
        "commands": [{
            "id": "impactSearch",
            "type": "query",
            "title": "영향 분석",
            "description": "오브젝트를 찾아 영향 분석 카드를 삽입합니다.",
            "initialRun": False,
            "context": ["compose", "commandBox"],
            "parameters": [{
                "name": "objectName",
                "title": "오브젝트",
                "description": "예: ZORDER_HDR",
                "inputType": "text",
            }],
        }],
        "messageHandlers": [{
            "type": "link",
            "value": {"domains": [host]},
        }],
    }]


def main() -> int:
    parser = argparse.ArgumentParser(description="Teams 앱 패키지 빌드")
    parser.add_argument("--host", required=True,
                        help="서비스 호스트 (예: sap-impact.azurewebsites.net, 스킴 제외)")
    parser.add_argument("--app-id", required=True, help="Teams 앱 ID (신규 GUID)")
    parser.add_argument("--developer", default="IT", help="개발자/조직 표시 이름")
    parser.add_argument("--bot-id", default="",
                        help="Azure Bot 앱 ID. 지정 시 봇·메시지 확장 기능 포함")
    parser.add_argument("--sso-client-id", default="",
                        help="Entra 앱 클라이언트 ID. 지정 시 탭 SSO(webApplicationInfo) 포함")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--out", default=os.path.join(HERE, "sap-impact-teams-app.zip"))
    args = parser.parse_args()

    if not GUID_RE.match(args.app_id):
        raise SystemExit("--app-id 는 GUID 형식이어야 합니다. 예: python -c \"import uuid;print(uuid.uuid4())\"")
    if args.host.startswith("http"):
        raise SystemExit("--host 에는 스킴 없이 호스트만 입력하세요 (예: contoso.azurewebsites.net)")

    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        raw = fh.read()
    manifest = json.loads(substitute(raw, {
        "APP_ID": args.app_id,
        "HOST": args.host,
        "DEVELOPER_NAME": args.developer,
    }))
    manifest["version"] = args.version

    if args.bot_id:
        if not GUID_RE.match(args.bot_id):
            raise SystemExit("--bot-id 는 GUID 형식이어야 합니다.")
        add_bot(manifest, args.bot_id, args.host)

    if args.sso_client_id:
        manifest["webApplicationInfo"] = {
            "id": args.sso_client_id,
            "resource": f"api://{args.host}/{args.sso_client_id}",
        }

    leftovers = re.findall(r"\$\{\{(\w+)\}\}", json.dumps(manifest))
    if leftovers:
        raise SystemExit(f"치환되지 않은 값이 남아 있습니다: {', '.join(sorted(set(leftovers)))}")

    missing = [icon for icon in ICONS if not os.path.exists(os.path.join(HERE, icon))]
    if missing:
        raise SystemExit(f"아이콘 없음: {', '.join(missing)} — python make_icons.py 로 생성하세요.")

    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for icon in ICONS:
            zf.write(os.path.join(HERE, icon), icon)

    capabilities = ["개인 탭", "채널 탭"]
    if args.bot_id:
        capabilities += ["봇", "메시지 확장/링크 언퍼링"]
    if args.sso_client_id:
        capabilities.append("탭 SSO")
    print(f"패키지 생성: {args.out}")
    print(f"포함 기능: {', '.join(capabilities)}")
    print("업로드: Teams > 앱 > 앱 관리 > 앱 업로드 (또는 조직 카탈로그 제출)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
