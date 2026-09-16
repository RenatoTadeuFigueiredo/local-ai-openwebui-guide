from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path


TOOL_MODULE = Path(__file__).parents[1] / "openwebui" / "browser_hitl_tool.py"
spec = importlib.util.spec_from_file_location("browser_hitl_tool", TOOL_MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_takeover_uses_tool_scoped_execute_panel_without_url_in_model_context(monkeypatch) -> None:
    tool = module.Tools()
    portal_url = "http://127.0.0.1:3210/takeover/sentinel-secret-token"
    monkeypatch.setattr(
        tool,
        "_request",
        lambda *_args, **_kwargs: {
            "session_id": "session-a",
            "state": "WAITING_FOR_HUMAN",
            "epoch": 2,
            "portal_url": portal_url,
            "expires_at": 123456,
        },
    )
    events: list[dict] = []

    async def emitter(event: dict) -> None:
        events.append(event)

    response, context = asyncio.run(
        tool.browser_request_human_control(
            "session-a",
            1,
            reason="Login required",
            __user__={"id": "user-a"},
            __event_emitter__=emitter,
        )
    )

    execute = [event for event in events if event.get("type") == "execute"]
    assert len(execute) == 1
    code = execute[0]["data"]["code"]
    assert portal_url in code
    assert "browser-hitl-takeover-panel" in code
    assert "document.createElement('a')" in code
    assert "noopener noreferrer" in code
    assert "window.open" not in code
    assert portal_url not in response.body.decode("utf-8")
    assert portal_url not in json.dumps(context)
    assert context["status"] == "WAITING_FOR_HUMAN"


def test_execute_panel_encodes_untrusted_reason_as_javascript_string(monkeypatch) -> None:
    tool = module.Tools()
    monkeypatch.setattr(
        tool,
        "_request",
        lambda *_args, **_kwargs: {
            "session_id": "session-a",
            "state": "WAITING_FOR_HUMAN",
            "epoch": 2,
            "portal_url": "http://127.0.0.1:3210/takeover/sentinel",
        },
    )
    events: list[dict] = []

    async def emitter(event: dict) -> None:
        events.append(event)

    reason = "</script>';globalThis.pwned=true;//"
    asyncio.run(
        tool.browser_request_human_control(
            "session-a",
            1,
            reason=reason,
            __event_emitter__=emitter,
        )
    )
    code = next(event["data"]["code"] for event in events if event["type"] == "execute")
    assert f"text.textContent = {json.dumps(reason)};" in code
    assert "innerHTML" not in code
