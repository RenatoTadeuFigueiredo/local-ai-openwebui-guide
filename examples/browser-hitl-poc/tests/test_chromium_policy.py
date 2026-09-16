from __future__ import annotations

import json
from pathlib import Path


def test_chromium_policy_blocks_local_browser_surfaces_and_proxy_bypasses() -> None:
    policy_path = Path(__file__).parents[1] / "chromium-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))

    assert "DeveloperToolsAvailability" not in policy
    assert policy["QuicAllowed"] is False
    assert policy["WebRtcIPHandlingPolicy"] == "disable_non_proxied_udp"
    assert {
        "file://*",
        "filesystem://*",
        "chrome://*",
        "chrome-extension://*",
        "devtools://*",
        "view-source:*",
    } <= set(policy["URLBlocklist"])
