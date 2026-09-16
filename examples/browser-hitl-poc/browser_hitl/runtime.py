from __future__ import annotations

import asyncio
import os
import secrets
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

from .settings import Settings
from .store import Store


class RuntimeUnavailable(RuntimeError):
    pass


@dataclass
class BrowserRuntime:
    session_id: str
    user_id: str
    profile_id: str
    slot: int
    display: str
    cdp_port: int
    vnc_port: int
    novnc_port: int
    proxy_port: int
    profile_dir: Path
    runtime_dir: Path
    xvfb: subprocess.Popen[bytes]
    chromium: subprocess.Popen[bytes]
    x11vnc: subprocess.Popen[bytes] | None
    websockify: subprocess.Popen[bytes] | None
    egress_proxy: subprocess.Popen[bytes]
    password_file: Path
    playwright_browser: Browser | None = None
    active_page: Page | None = None


class RuntimeManager:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self._runtimes: dict[str, BrowserRuntime] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self._playwright: Any = None

    async def start(self) -> None:
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def stop(self) -> None:
        for task in self._expiry_tasks.values():
            task.cancel()
        await asyncio.gather(*self._expiry_tasks.values(), return_exceptions=True)
        self._expiry_tasks.clear()
        for session_id in list(self._runtimes):
            await self.stop_session(session_id)
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def _runtime_paths(self, session: dict[str, Any]) -> tuple[Path, Path]:
        profile_dir = self.settings.profiles_dir / str(session["profile_id"])
        runtime_dir = self.settings.runtime_dir / str(session["session_id"])
        for path in (profile_dir, runtime_dir):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        return profile_dir, runtime_dir

    def _ports(self, slot: int) -> tuple[int, int, int, int, str]:
        return (
            self.settings.cdp_port_start + slot,
            self.settings.vnc_port_start + slot,
            self.settings.novnc_port_start + slot,
            self.settings.proxy_port_start + slot,
            f":{self.settings.display_start + slot}",
        )

    @staticmethod
    def _prepare_display(display: str, tmp_root: Path = Path("/tmp")) -> None:
        """Remove only stale X artifacts for the deterministic private display."""
        number = display.removeprefix(":").split(".", 1)[0]
        lock_path = tmp_root / f".X{number}-lock"
        socket_path = tmp_root / ".X11-unix" / f"X{number}"
        if not lock_path.exists() and not socket_path.exists():
            return

        # A live UNIX socket is authoritative even if a lock PID was reused or
        # malformed. Never remove artifacts for a display that accepts X traffic.
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(socket_path))
        except OSError:
            pass
        else:
            raise RuntimeUnavailable(f"X display {display} is already active")
        finally:
            probe.close()

        for path in (lock_path, socket_path):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                raise RuntimeUnavailable(f"Cannot clear stale X display artifact: {path}") from error

    @staticmethod
    def _port_ready(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            return False

    async def _wait_port(
        self,
        process: subprocess.Popen[bytes],
        port: int,
        label: str,
        timeout: float = 15,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeUnavailable(f"{label} exited before listening")
            if self._port_ready(port):
                return
            await asyncio.sleep(0.1)
        raise RuntimeUnavailable(f"{label} did not listen on 127.0.0.1:{port}")

    @staticmethod
    def _start_process(args: list[str], *, env: dict[str, str], log: Path) -> subprocess.Popen[bytes]:
        log.touch(mode=0o600, exist_ok=True)
        log.chmod(0o600)
        handle = log.open("ab", buffering=0)
        try:
            return subprocess.Popen(
                args,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            handle.close()

    @staticmethod
    def _alive(runtime: BrowserRuntime) -> bool:
        # The VNC viewer is intentionally ephemeral and may be stopped after the
        # human returns control. Chromium, Xvfb, and the egress proxy define the
        # persistent browser runtime.
        return all(
            process.poll() is None
            for process in (runtime.xvfb, runtime.chromium, runtime.egress_proxy)
        )

    async def ensure(self, session: dict[str, Any]) -> BrowserRuntime:
        session_id = str(session["session_id"])
        async with self._lock(session_id):
            return await self._ensure_unlocked(session)

    async def _ensure_unlocked(self, session: dict[str, Any]) -> BrowserRuntime:
        session_id = str(session["session_id"])
        current = self._runtimes.get(session_id)
        if current and self._alive(current):
            return current
        if current:
            await self._stop_runtime(current)

        await self.start()
        profile_dir, runtime_dir = self._runtime_paths(session)
        slot = int(session["runtime_slot"])
        cdp_port, vnc_port, novnc_port, proxy_port, display = self._ports(slot)
        env = os.environ.copy()
        env["DISPLAY"] = display
        self._prepare_display(display)

        for stale in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                (profile_dir / stale).unlink(missing_ok=True)
            except OSError:
                pass

        password_file = runtime_dir / "vnc.pass"
        password_file.write_text(secrets.token_urlsafe(18) + "\n", encoding="utf-8")
        password_file.chmod(0o600)

        started: list[subprocess.Popen[bytes]] = []
        try:
            xvfb = self._start_process(
                [
                    self.settings.xvfb_bin,
                    display,
                    "-screen",
                    "0",
                    "1440x900x24",
                    "-nolisten",
                    "tcp",
                    "-noreset",
                ],
                env=env,
                log=runtime_dir / "xvfb.log",
            )
            started.append(xvfb)
            await asyncio.sleep(0.3)
            if xvfb.poll() is not None:
                raise RuntimeUnavailable("Xvfb failed to start")

            egress_proxy = self._start_process(
                [
                    "/home/cptr/.venv/bin/python",
                    "-m",
                    "browser_hitl.egress_proxy",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(proxy_port),
                ],
                env=env,
                log=runtime_dir / "proxy.log",
            )
            started.append(egress_proxy)
            await self._wait_port(egress_proxy, proxy_port, "egress proxy")

            chromium = self._start_process(
                [
                    self.settings.chromium_bin,
                    f"--remote-debugging-port={cdp_port}",
                    "--remote-debugging-address=127.0.0.1",
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--disable-extensions",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-password-generation",
                    "--disable-features=PasswordManagerOnboarding,PasswordLeakDetection",
                    f"--proxy-server=http://127.0.0.1:{proxy_port}",
                    "--proxy-bypass-list=<-loopback>",
                    "--window-size=1440,900",
                    str(session.get("current_url") or "about:blank"),
                ],
                env=env,
                log=runtime_dir / "chromium.log",
            )
            started.append(chromium)
            await self._wait_port(chromium, cdp_port, "Chromium CDP", timeout=25)

            # The remote viewer is not started during agent control. x11vnc and
            # websockify exist only while a redeemed human takeover is active.
            x11vnc = None
            websockify = None
        except Exception:
            await self._terminate_processes(reversed(started))
            password_file.unlink(missing_ok=True)
            raise

        runtime = BrowserRuntime(
            session_id=session_id,
            user_id=str(session["user_id"]),
            profile_id=str(session["profile_id"]),
            slot=slot,
            display=display,
            cdp_port=cdp_port,
            vnc_port=vnc_port,
            novnc_port=novnc_port,
            proxy_port=proxy_port,
            profile_dir=profile_dir,
            runtime_dir=runtime_dir,
            xvfb=xvfb,
            chromium=chromium,
            x11vnc=x11vnc,
            websockify=websockify,
            egress_proxy=egress_proxy,
            password_file=password_file,
        )
        self._runtimes[session_id] = runtime
        return runtime

    async def _browser(self, runtime: BrowserRuntime) -> Browser:
        await self.start()
        if runtime.playwright_browser and runtime.playwright_browser.is_connected():
            return runtime.playwright_browser
        runtime.playwright_browser = await self._playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{runtime.cdp_port}"
        )
        return runtime.playwright_browser

    async def _page(self, runtime: BrowserRuntime) -> Page:
        if runtime.active_page and not runtime.active_page.is_closed():
            return runtime.active_page
        browser = await self._browser(runtime)
        if not browser.contexts:
            raise RuntimeUnavailable("Managed Chromium has no browser context")
        pages = browser.contexts[0].pages
        meaningful = [page for page in pages if page.url and page.url != "about:blank"]
        runtime.active_page = (meaningful or pages)[-1] if pages else await browser.contexts[0].new_page()
        return runtime.active_page

    async def navigate(self, session: dict[str, Any], url: str) -> dict[str, Any]:
        session_id = str(session["session_id"])
        user_id = str(session["user_id"])
        epoch = int(session["epoch"])
        async with self._lock(session_id):
            self.store.assert_agent(session_id, user_id, epoch)
            runtime = await self._ensure_unlocked(session)
            page = await self._page(runtime)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self.store.assert_agent(session_id, user_id, epoch)
            current_url = page.url
            self.store.set_url(session_id, user_id, epoch, current_url)
            self.store.audit(
                event="agent.navigate", user_id=user_id, session_id=session_id, epoch=epoch
            )
            return {
                "session_id": session_id,
                "epoch": epoch,
                "url": current_url,
                "title": await page.title(),
                "status": response.status if response else None,
            }

    async def snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session["session_id"])
        user_id = str(session["user_id"])
        epoch = int(session["epoch"])
        async with self._lock(session_id):
            self.store.assert_agent(session_id, user_id, epoch)
            runtime = await self._ensure_unlocked(session)
            page = await self._page(runtime)
            payload = await page.evaluate(
                """() => ({
                    title: document.title,
                    url: location.href,
                    body_text: (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 12000),
                    elements: Array.from(document.querySelectorAll('a,button,input,textarea,select,[role="button"]'))
                      .slice(0, 180)
                      .map((el, index) => ({
                        index,
                        tag: el.tagName.toLowerCase(),
                        type: el.getAttribute('type') || '',
                        name: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 160),
                        selector: el.id ? '#' + CSS.escape(el.id) : ''
                      }))
                })"""
            )
            self.store.assert_agent(session_id, user_id, epoch)
            self.store.audit(
                event="agent.snapshot", user_id=user_id, session_id=session_id, epoch=epoch
            )
            return {"session_id": session_id, "epoch": epoch, **payload}

    async def click(self, session: dict[str, Any], selector: str) -> dict[str, Any]:
        session_id = str(session["session_id"])
        user_id = str(session["user_id"])
        epoch = int(session["epoch"])
        async with self._lock(session_id):
            self.store.assert_agent(session_id, user_id, epoch)
            runtime = await self._ensure_unlocked(session)
            page = await self._page(runtime)
            await page.click(selector, timeout=10_000)
            self.store.assert_agent(session_id, user_id, epoch)
            return {
                "session_id": session_id,
                "epoch": epoch,
                "url": page.url,
                "clicked": selector,
            }

    async def type_text(
        self,
        session: dict[str, Any],
        selector: str,
        text: str,
        submit: bool,
    ) -> dict[str, Any]:
        session_id = str(session["session_id"])
        user_id = str(session["user_id"])
        epoch = int(session["epoch"])
        async with self._lock(session_id):
            self.store.assert_agent(session_id, user_id, epoch)
            runtime = await self._ensure_unlocked(session)
            page = await self._page(runtime)
            await page.fill(selector, text, timeout=10_000)
            if submit:
                await page.press(selector, "Enter")
            self.store.assert_agent(session_id, user_id, epoch)
            return {
                "session_id": session_id,
                "epoch": epoch,
                "url": page.url,
                "typed": selector,
                "text_length": len(text),
                "submitted": submit,
            }

    async def begin_takeover(
        self,
        session_id: str,
        user_id: str,
        user_email: str,
        epoch: int,
        ttl_seconds: int,
    ) -> tuple[str, dict[str, Any], dict[str, Any], BrowserRuntime]:
        async with self._lock(session_id):
            session = self.store.assert_agent(session_id, user_id, epoch)
            runtime = await self._ensure_unlocked(session)
            token, grant, updated = self.store.issue_takeover(
                session_id,
                user_id,
                epoch,
                ttl_seconds,
                user_email=user_email,
            )
            # The broker keeps the same CDP attachment and tab object, but every
            # action/observation path is fenced by the durable state and this
            # per-session lock. No automation call can run in HUMAN_ACTIVE.
            return token, grant, updated, runtime

    async def viewer(self, session: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session["session_id"])
        async with self._lock(session_id):
            # Re-check durable ownership after waiting for another viewer or a
            # completion request. This prevents a late HTTP/WebSocket request
            # from restarting VNC after control was returned to the agent.
            self.store.assert_human(session_id, int(session["epoch"]))
            runtime = await self._ensure_unlocked(session)
            if (
                not runtime.x11vnc
                or runtime.x11vnc.poll() is not None
                or not runtime.websockify
                or runtime.websockify.poll() is not None
            ):
                env = os.environ.copy()
                env["DISPLAY"] = runtime.display
                runtime.x11vnc = self._start_process(
                    [
                        self.settings.x11vnc_bin,
                        "-display",
                        runtime.display,
                        "-rfbport",
                        str(runtime.vnc_port),
                        "-listen",
                        "127.0.0.1",
                        "-forever",
                        "-shared",
                        "-noclipboard",
                        "-nosetclipboard",
                        "-passwdfile",
                        str(runtime.password_file),
                    ],
                    env=env,
                    log=runtime.runtime_dir / "vnc.log",
                )
                try:
                    await self._wait_port(runtime.x11vnc, runtime.vnc_port, "x11vnc")
                    runtime.websockify = self._start_process(
                        [
                            self.settings.websockify_bin,
                            "--web",
                            self.settings.novnc_web_root,
                            f"127.0.0.1:{runtime.novnc_port}",
                            f"127.0.0.1:{runtime.vnc_port}",
                        ],
                        env=env,
                        log=runtime.runtime_dir / "vnc.log",
                    )
                    await self._wait_port(runtime.websockify, runtime.novnc_port, "websockify")
                except Exception:
                    await self._terminate_processes(
                        process
                        for process in (runtime.websockify, runtime.x11vnc)
                        if process is not None
                    )
                    runtime.websockify = None
                    runtime.x11vnc = None
                    raise
        return {
            "novnc_port": runtime.novnc_port,
            "password": runtime.password_file.read_text(encoding="utf-8").strip(),
        }

    async def stop_viewer_unlocked(self, session_id: str) -> None:
        """Stop the takeover transport while the caller owns the session lock."""
        runtime = self._runtimes.get(session_id)
        if not runtime:
            return
        await self._terminate_processes(
            process for process in (runtime.websockify, runtime.x11vnc) if process is not None
        )
        runtime.websockify = None
        runtime.x11vnc = None

    async def stop_viewer(self, session_id: str) -> None:
        async with self._lock(session_id):
            await self.stop_viewer_unlocked(session_id)

    def schedule_takeover_expiry(
        self,
        grant_id: str,
        session_id: str,
        active_expires_at: int,
    ) -> None:
        current = self._expiry_tasks.pop(session_id, None)
        if current:
            current.cancel()

        async def expire() -> None:
            try:
                await asyncio.sleep(max(0, active_expires_at - int(time.time())))
                for attempt in range(3):
                    try:
                        await self.expire_takeover(grant_id, session_id)
                        return
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        self.store.audit(
                            event="takeover.expire_retry",
                            user_id=None,
                            session_id=session_id,
                            epoch=None,
                            outcome="error",
                            detail=f"attempt={attempt + 1} type={type(error).__name__}",
                        )
                        if attempt < 2:
                            await asyncio.sleep(2**attempt)
            except asyncio.CancelledError:
                return
            finally:
                if self._expiry_tasks.get(session_id) is asyncio.current_task():
                    self._expiry_tasks.pop(session_id, None)

        self._expiry_tasks[session_id] = asyncio.create_task(expire())

    def cancel_takeover_expiry(self, session_id: str) -> None:
        task = self._expiry_tasks.pop(session_id, None)
        if task:
            task.cancel()

    async def abort_active_takeovers(self) -> int:
        sessions = self.store.active_takeover_sessions()

        async def abort(session: dict[str, Any]) -> None:
            session_id = str(session["session_id"])
            self.cancel_takeover_expiry(session_id)
            async with self._lock(session_id):
                self.store.abort_takeover(session_id)
                await self.stop_viewer_unlocked(session_id)

        await asyncio.gather(*(abort(session) for session in sessions))
        return len(sessions)

    async def expire_takeover(self, grant_id: str, session_id: str) -> None:
        async with self._lock(session_id):
            self.store.expire_active_grant(grant_id)
            await self.stop_viewer_unlocked(session_id)

    async def complete_takeover(
        self,
        grant_id: str,
        session_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        async with self._lock(session_id):
            grant, session = self.store.complete_takeover(grant_id)
            self.cancel_takeover_expiry(session_id)
            await self.stop_viewer_unlocked(session_id)
            return grant, session

    async def resume_agent(self, session_id: str, user_id: str) -> dict[str, Any]:
        async with self._lock(session_id):
            # Keep durable ownership in READY_TO_RESUME until Chromium is known
            # usable. A startup failure therefore cannot publish an unusable
            # AGENT_ACTIVE lease; the caller may safely retry recovery.
            ready = self.store.assert_ready_to_resume(session_id, user_id)
            await self.stop_viewer_unlocked(session_id)
            await self._ensure_unlocked(ready)
            return self.store.resume_agent(session_id, user_id)

    async def stop_session(self, session_id: str) -> None:
        self.cancel_takeover_expiry(session_id)
        async with self._lock(session_id):
            runtime = self._runtimes.pop(session_id, None)
            if runtime:
                await self._stop_runtime(runtime)

    async def _stop_runtime(self, runtime: BrowserRuntime) -> None:
        await self._terminate_processes(
            (
                *([runtime.websockify] if runtime.websockify else []),
                *([runtime.x11vnc] if runtime.x11vnc else []),
                runtime.chromium,
                runtime.xvfb,
                runtime.egress_proxy,
            )
        )
        runtime.password_file.unlink(missing_ok=True)

    @staticmethod
    async def _terminate_processes(processes: Any) -> None:
        process_list = list(processes)
        for process in process_list:
            if process is None or process.poll() is not None:
                continue
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if all(process is None or process.poll() is not None for process in process_list):
                return
            await asyncio.sleep(0.1)
        for process in process_list:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
