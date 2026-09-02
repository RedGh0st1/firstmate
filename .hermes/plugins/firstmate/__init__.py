"""Hermes primary adapter for a Firstmate checkout."""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path


LOGGER = logging.getLogger("firstmate.hermes")
_FOLLOWUP_LOCK = threading.Lock()
_FOLLOWUP_SENT = False
_ARM_LOCK = threading.Lock()
_ARM_PROC: subprocess.Popen[str] | None = None
_SHUTTING_DOWN = False
_ARM_RETRY_FAILURES = 0
_INJECT_LOCK = threading.Lock()
_ACTIONABLE_WAKE = re.compile(r"^(?:signal:|stale:|check:|heartbeat($|:))")


def _positive_int(name: str, fallback: int) -> int:
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return fallback
    return value if value > 0 else fallback


_REARM_RETRY_LIMIT = _positive_int("FM_WATCH_REARM_RETRY_LIMIT", 5)
_REARM_RETRY_BASE_S = _positive_int("FM_WATCH_REARM_RETRY_BASE_MS", 250) / 1000.0
_REARM_RETRY_MAX_S = _positive_int("FM_WATCH_REARM_RETRY_MAX_MS", 4000) / 1000.0


def _retry_delay(attempt: int) -> float:
    return min(_REARM_RETRY_MAX_S, _REARM_RETRY_BASE_S * 2 ** max(0, attempt - 1))


def _inject(ctx, message: str) -> None:
    with _INJECT_LOCK:
        try:
            ctx.inject_message(message, role="user")
        except Exception as exc:
            LOGGER.error("Firstmate Hermes message injection failed: %s", exc)


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["FM_ROOT_OVERRIDE"] = str(root)
    env["FM_HOME"] = str(root)
    return env


def _firstmate_root(root: Path) -> bool:
    return (root / "AGENTS.md").is_file() and (root / "bin" / "fm-watch-arm.sh").is_file()


_WATCHER_WAKE_INSTRUCTION = (
    "WATCHER FIRED - drain queued wakes with bin/fm-wake-drain.sh and handle the "
    "reported wake. Watcher continuity is plugin-owned."
)


def _watcher_message(root: Path, wake: str) -> str | None:
    body = "%s\n\n%s" % (_WATCHER_WAKE_INSTRUCTION, wake)
    encoded = subprocess.run(
        [str(root / "bin" / "fm-operational-input.sh"), "encode", "watcher"],
        cwd=root,
        env=_environment(root),
        input=body + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if encoded.returncode != 0 or not encoded.stdout.strip():
        LOGGER.error("Firstmate Hermes watcher wake could not be encoded")
        return None
    return encoded.stdout.strip()


def _monitor_arm(root: Path, ctx, proc: subprocess.Popen[str]) -> None:
    wake: str | None = None
    if proc.stdout is not None:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if _ACTIONABLE_WAKE.match(line) and wake is None:
                wake = line
                message = _watcher_message(root, line)
                if message is not None:
                    _inject(ctx, message)
    returncode = proc.wait()
    with _ARM_LOCK:
        if _ARM_PROC is proc:
            globals()["_ARM_PROC"] = None
        shutting_down = _SHUTTING_DOWN
        if returncode == 0 or wake is not None:
            globals()["_ARM_RETRY_FAILURES"] = 0
            failures = 0
        else:
            failures = _ARM_RETRY_FAILURES + 1
            globals()["_ARM_RETRY_FAILURES"] = failures
    if shutting_down:
        return
    if failures:
        LOGGER.warning(
            "Firstmate Hermes watcher arm exited with status %s (re-arm attempt %s/%s)",
            returncode,
            failures,
            _REARM_RETRY_LIMIT,
        )
        if failures > _REARM_RETRY_LIMIT:
            message = _watcher_message(
                root,
                "FAILED - firstmate watcher re-arm failed %d consecutive times; "
                "supervision is down until the watcher is re-armed" % _REARM_RETRY_LIMIT,
            )
            if message is not None:
                _inject(ctx, message)
            return
        delay = _retry_delay(failures)
    else:
        delay = _REARM_RETRY_BASE_S
    time.sleep(delay)
    with _ARM_LOCK:
        if _SHUTTING_DOWN:
            return
    _arm(root, ctx)


def _arm(root: Path, ctx) -> None:
    global _ARM_PROC
    with _ARM_LOCK:
        if _SHUTTING_DOWN:
            return
        if _ARM_PROC is not None and _ARM_PROC.poll() is None:
            return
        try:
            _ARM_PROC = subprocess.Popen(
                [str(root / "bin" / "fm-watch-arm.sh")],
                cwd=root,
                env=_environment(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            proc = _ARM_PROC
        except OSError as exc:
            LOGGER.error("Firstmate Hermes watcher arm failed: %s", exc)
            return
    threading.Thread(
        target=_monitor_arm,
        args=(root, ctx, proc),
        name="firstmate-hermes-watcher",
        daemon=True,
    ).start()


def _disarm() -> None:
    global _ARM_PROC, _SHUTTING_DOWN
    with _ARM_LOCK:
        _SHUTTING_DOWN = True
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
        with _ARM_LOCK:
            globals()["_ARM_RETRY_FAILURES"] = 0
        _arm(root, ctx)

    def on_session_end(**kwargs) -> None:
        del kwargs
        global _FOLLOWUP_SENT
        _arm(root, ctx)
        if not _guard(root):
            return
        with _FOLLOWUP_LOCK:
            if _FOLLOWUP_SENT:
                return
            _FOLLOWUP_SENT = True
        message = _followup(root)
        if message is not None:
            _inject(ctx, message)

    ctx.register_hook("on_stream_start", on_stream_start)
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("on_session_end", on_session_end)
