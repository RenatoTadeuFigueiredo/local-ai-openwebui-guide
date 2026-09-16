from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    root: Path
    host: str
    port: int
    public_base_url: str
    public_host: str
    access_required: bool
    access_team_domain: str
    access_audience: str
    takeover_ttl_seconds: int
    human_control_ttl_seconds: int
    session_idle_seconds: int
    display_start: int
    cdp_port_start: int
    vnc_port_start: int
    novnc_port_start: int
    proxy_port_start: int
    chromium_bin: str
    xvfb_bin: str
    x11vnc_bin: str
    websockify_bin: str
    novnc_web_root: str
    browser_policy_file: str

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.environ.get("BROWSER_HITL_ROOT", "/data/browser-hitl"))
        public_base_url = os.environ.get(
            "BROWSER_HITL_PUBLIC_BASE_URL", "http://127.0.0.1:3210"
        ).rstrip("/")
        parsed = urlsplit(public_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise RuntimeError("BROWSER_HITL_PUBLIC_BASE_URL must be an HTTP(S) origin without a path")

        public_host = os.environ.get("BROWSER_HITL_PUBLIC_HOST", parsed.hostname).strip().casefold()
        if public_host != parsed.hostname.casefold():
            raise RuntimeError("BROWSER_HITL_PUBLIC_HOST must match BROWSER_HITL_PUBLIC_BASE_URL")

        access_required = _env_bool("BROWSER_HITL_ACCESS_REQUIRED")
        access_team_domain = os.environ.get("BROWSER_HITL_ACCESS_TEAM_DOMAIN", "").rstrip("/")
        access_audience = os.environ.get("BROWSER_HITL_ACCESS_AUDIENCE", "").strip()
        remote_portal = not _is_loopback_host(public_host)

        if remote_portal and parsed.scheme != "https":
            raise RuntimeError("A remote Browser HITL portal requires HTTPS")
        if remote_portal and not access_required:
            raise RuntimeError("A remote Browser HITL portal requires Cloudflare Access validation")
        if access_required:
            team = urlsplit(access_team_domain)
            if (
                team.scheme != "https"
                or not team.hostname
                or not team.hostname.endswith(".cloudflareaccess.com")
                or team.path not in {"", "/"}
                or team.query
                or team.fragment
            ):
                raise RuntimeError("BROWSER_HITL_ACCESS_TEAM_DOMAIN must be an HTTPS Cloudflare Access team origin")
            if not access_audience or len(access_audience) > 256:
                raise RuntimeError("BROWSER_HITL_ACCESS_AUDIENCE is required when Access validation is enabled")

        human_control_ttl_seconds = int(
            os.environ.get("BROWSER_HITL_HUMAN_CONTROL_TTL_SECONDS", "3600")
        )
        if not 60 <= human_control_ttl_seconds <= 3600:
            raise RuntimeError(
                "BROWSER_HITL_HUMAN_CONTROL_TTL_SECONDS must be between 60 and 3600"
            )

        return cls(
            root=root,
            host=os.environ.get("BROWSER_HITL_HOST", "127.0.0.1"),
            port=int(os.environ.get("BROWSER_HITL_PORT", "3210")),
            public_base_url=public_base_url,
            public_host=public_host,
            access_required=access_required,
            access_team_domain=access_team_domain,
            access_audience=access_audience,
            takeover_ttl_seconds=int(os.environ.get("BROWSER_HITL_TAKEOVER_TTL_SECONDS", "300")),
            human_control_ttl_seconds=human_control_ttl_seconds,
            session_idle_seconds=int(os.environ.get("BROWSER_HITL_SESSION_IDLE_SECONDS", "14400")),
            display_start=int(os.environ.get("BROWSER_HITL_DISPLAY_START", "90")),
            cdp_port_start=int(os.environ.get("BROWSER_HITL_CDP_PORT_START", "9320")),
            vnc_port_start=int(os.environ.get("BROWSER_HITL_VNC_PORT_START", "5920")),
            novnc_port_start=int(os.environ.get("BROWSER_HITL_NOVNC_PORT_START", "6090")),
            proxy_port_start=int(os.environ.get("BROWSER_HITL_PROXY_PORT_START", "8890")),
            chromium_bin=os.environ.get("BROWSER_HITL_CHROMIUM_BIN", "/usr/bin/chromium"),
            xvfb_bin=os.environ.get("BROWSER_HITL_XVFB_BIN", "/usr/bin/Xvfb"),
            x11vnc_bin=os.environ.get("BROWSER_HITL_X11VNC_BIN", "/usr/bin/x11vnc"),
            websockify_bin=os.environ.get("BROWSER_HITL_WEBSOCKIFY_BIN", "/usr/bin/websockify"),
            novnc_web_root=os.environ.get("BROWSER_HITL_NOVNC_WEB_ROOT", "/usr/share/novnc"),
            browser_policy_file=os.environ.get(
                "BROWSER_HITL_BROWSER_POLICY_FILE",
                "/etc/chromium/policies/managed/browser-hitl.json",
            ),
        )

    @property
    def remote_portal(self) -> bool:
        return not _is_loopback_host(self.public_host)

    @property
    def state_db(self) -> Path:
        return self.root / "state" / "broker.db"

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def audit_log(self) -> Path:
        return self.root / "logs" / "audit.jsonl"

    def ensure_dirs(self) -> None:
        # Keep newly created DB, audit, runtime, and profile artifacts private
        # even before their explicit chmod calls.
        os.umask(0o077)
        for path in (
            self.root,
            self.state_db.parent,
            self.profiles_dir,
            self.runtime_dir,
            self.audit_log.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
