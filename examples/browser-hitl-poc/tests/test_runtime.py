from __future__ import annotations

import socket
from pathlib import Path

import pytest

from browser_hitl.runtime import RuntimeManager, RuntimeUnavailable


def display_paths(tmp_path: Path, number: int) -> tuple[Path, Path]:
    return tmp_path / f".X{number}-lock", tmp_path / ".X11-unix" / f"X{number}"


def test_prepare_display_removes_stale_lock_and_socket(tmp_path: Path) -> None:
    number = 7000
    lock_path, socket_path = display_paths(tmp_path, number)
    lock_path.write_text("999999\n", encoding="utf-8")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.touch()

    RuntimeManager._prepare_display(f":{number}", tmp_path)

    assert not lock_path.exists()
    assert not socket_path.exists()


def test_prepare_display_never_removes_live_x_socket(tmp_path: Path) -> None:
    number = 7001
    lock_path, socket_path = display_paths(tmp_path, number)
    lock_path.write_text("123\n", encoding="utf-8")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    try:
        with pytest.raises(RuntimeUnavailable, match="already active"):
            RuntimeManager._prepare_display(f":{number}", tmp_path)
        assert lock_path.exists()
        assert socket_path.exists()
    finally:
        listener.close()
