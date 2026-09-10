"""
Foundry agent proxy for the web app.

The React app talks to the agent through the service instead of calling Foundry
from the browser, for one reason: the browser would otherwise need a token for
the Foundry project. Here the container's managed identity holds that
credential, and the browser only ever sees text.

The agent is the one this repo registers (service/foundry_agent.py): it has the
impact API as an OpenAPI tool and instructions that forbid naming objects the
tool did not return. So the chat panel and the dashboards are reading the same
graph -- the agent cannot answer from somewhere else.
"""

import json
import os
import queue
import threading
from typing import Any, Dict, Iterator, Optional

PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
AGENT_NAME = os.environ.get("FOUNDRY_AGENT_NAME", "sap-change-impact")

_client_lock = threading.Lock()
_openai_client = None


class AgentUnavailable(RuntimeError):
    """Raised with a message the UI can show verbatim."""


def configured() -> bool:
    return bool(PROJECT_ENDPOINT)


def _client():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if not PROJECT_ENDPOINT:
        raise AgentUnavailable(
            "Foundry 에이전트가 설정되지 않았습니다. FOUNDRY_PROJECT_ENDPOINT 환경변수를 지정하세요.")
    with _client_lock:
        if _openai_client is None:
            try:
                from azure.ai.projects import AIProjectClient
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:
                raise AgentUnavailable(
                    "azure-ai-projects / azure-identity 패키지가 필요합니다.") from exc
            try:
                project = AIProjectClient(endpoint=PROJECT_ENDPOINT,
                                          credential=DefaultAzureCredential())
                _openai_client = project.get_openai_client(agent_name=AGENT_NAME)
            except Exception as exc:
                raise AgentUnavailable(f"Foundry 연결 실패: {exc}") from exc
    return _openai_client


def new_conversation() -> str:
    return _client().conversations.create().id


def stream_answer(message: str, conversation_id: Optional[str] = None,
                  context: Optional[Dict[str, Any]] = None) -> Iterator[str]:
    """
    Yield server-sent events: `delta` for text, `tool` when the agent calls the
    impact API (the UI shows which analysis backed the answer), `done` at the
    end, `error` if the agent is unreachable.
    """
    try:
        client = _client()
        if not conversation_id:
            conversation_id = client.conversations.create().id
        yield _sse("conversation", {"id": conversation_id})

        prompt = message
        if context:
            # The app knows what the user is looking at; the agent should not
            # have to ask "which workspace?" when the screen already says so.
            prompt = (f"[현재 화면 컨텍스트] {json.dumps(context, ensure_ascii=False)}\n\n"
                      f"{message}")

        stream = client.responses.create(
            conversation=conversation_id,
            input=prompt,
            stream=True,
            extra_body={"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
        )
        for event in stream:
            kind = getattr(event, "type", "")
            if kind == "response.output_text.delta":
                yield _sse("delta", {"text": getattr(event, "delta", "")})
            elif kind == "response.output_item.done":
                item = getattr(event, "item", None)
                if item is not None and getattr(item, "type", "") in (
                        "function_call", "tool_call", "mcp_call"):
                    yield _sse("tool", {"name": getattr(item, "name", "tool")})
            elif kind == "response.completed":
                yield _sse("done", {})
    except AgentUnavailable as exc:
        yield _sse("error", {"message": str(exc)})
    except Exception as exc:  # provider errors, auth failures, timeouts
        yield _sse("error", {"message": f"에이전트 호출 실패: {exc}"})


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
