"""Hermes primary adapter for a Firstmate checkout."""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import threading
from pathlib import Path


LOGGER = logging.getLogger("firstmate.hermes")
_FOLLOWUP_LOCK = threading.Lock()
_FOLLOWUP_SENT = False
_ARM_LOCK = threading.Lock()
_ARM_PROC: subprocess.Popen | None = None


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["FM_ROOT_OVERRIDE"] = str(root)
    env["FM_HOME"] = str(root)
    return env


def _firstmate_root(root: Path) -> bool:
    return (root / "AGENTS.md").is_file() and (root / "bin" / "fm-watch-arm.sh").is_file()


def _arm(root: Path) -> None:
    global _ARM_PROC
    with _ARM_LOCK:
        if _ARM_PROC is not None and _ARM_PROC.poll() is None:
            return
        try:
            _ARM_PROC = subprocess.Popen(
                [str(root / "bin" / "fm-watch-arm.sh")],
                cwd=root,
                env=_environment(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            LOGGER.error("Firstmate Hermes watcher arm failed: %s", exc)


def _disarm() -> None:
    global _ARM_PROC
    with _ARM_LOCK:
        proc, _ARM_PROC = _ARM_PROC, None
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


atexit.register(_disarm)


def _guard(root: Path) -> bool:
    guard = root / "bin" / "fm-turnend-guard.sh"
    try:
        result = subprocess.run(
            [str(guard)],
            cwd=root,
            env=_environment(root),
            input=json.dumps({"stop_hook_active": False}),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        LOGGER.error("Firstmate Hermes turn-end guard failed to run: %s", exc)
        return False
    if result.returncode == 2:
        return True
    if result.returncode != 0:
        LOGGER.warning("Firstmate Hermes turn-end guard returned %s", result.returncode)
    return False


def _followup(root: Path) -> str | None:
    repair = subprocess.run(
        [str(root / "bin" / "fm-supervision-instructions.sh"), "--harness", "hermes", "--repair-line"],
        cwd=root,
        env=_environment(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if repair.returncode != 0 or not repair.stdout.strip():
        LOGGER.error("Firstmate Hermes repair instruction could not be rendered")
        return None
    encoded = subprocess.run(
        [str(root / "bin" / "fm-operational-input.sh"), "encode", "turn-end-guard"],
        cwd=root,
        env=_environment(root),
        input=repair.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    if encoded.returncode != 0 or not encoded.stdout.strip():
        LOGGER.error("Firstmate Hermes operational follow-up could not be encoded")
        return None
    return encoded.stdout.strip()


def register(ctx) -> None:
    """Register the Hermes session lifecycle adapter."""
    root = _root()
    if not _firstmate_root(root):
        return

    def on_stream_start(**kwargs) -> None:
        del kwargs
        global _FOLLOWUP_SENT
        with _FOLLOWUP_LOCK:
            _FOLLOWUP_SENT = False

    def on_session_start(**kwargs) -> None:
        del kwargs
        _arm(root)

    def on_session_end(**kwargs) -> None:
        del kwargs
        global _FOLLOWUP_SENT
        _arm(root)
        if not _guard(root):
            return
        with _FOLLOWUP_LOCK:
            if _FOLLOWUP_SENT:
                return
            _FOLLOWUP_SENT = True
        message = _followup(root)
        if message is not None:
            ctx.inject_message(message, role="user")

    ctx.register_hook("on_stream_start", on_stream_start)
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("on_session_end", on_session_end)
