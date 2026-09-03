"""Hermes tools for the local no-mistakes CLI and AXI interface."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


_SECRET = re.compile(r"(?i)(?:gho_|github_pat_|token[=: ]+|authorization[=: ]+bearer\s+)[^\s,;]+")
_ROOT_READ = {"status", "doctor", "runs"}
_ROOT_MUTATE = {"init", "rerun", "update", "eject", "sync"}
_AXI_READ = {"status", "logs"}
_AXI_MUTATE = {"run", "respond", "abort", "sync"}


def _redact(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value)


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _workdir(args: dict[str, Any], kw: dict[str, Any]) -> Path:
    raw = args.get("workdir") or kw.get("cwd") or os.environ.get("TERMINAL_CWD") or os.getcwd()
    path = Path(str(raw)).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"workdir is not a directory: {path}")
    return path


def _result(argv: list[str], cwd: Path, timeout_s: int) -> str:
    binary = shutil.which("no-mistakes")
    if binary is None:
        return json.dumps({"ok": False, "error": "no-mistakes executable is not on PATH"})
    safe_argv = [_redact(str(x)) for x in argv]
    try:
        completed = subprocess.run(
            [binary, *argv],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        return json.dumps({
            "ok": False,
            "command": argv[0] if argv else "no-mistakes",
            "argv_redacted": safe_argv,
            "cwd": str(cwd),
            "timed_out": True,
            "timeout_s": timeout_s,
            "stdout": _redact(_text(exc.stdout)),
            "stderr": _redact(_text(exc.stderr)),
        })
    stdout = _redact(completed.stdout)
    stderr = _redact(completed.stderr)
    parsed: Any = None
    try:
        parsed = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        pass
    return json.dumps({
        "ok": completed.returncode == 0,
        "command": argv[0] if argv else "no-mistakes",
        "argv_redacted": safe_argv,
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "timed_out": False,
        "stdout": stdout,
        "stderr": stderr,
        "parsed": parsed,
    })


def _timeout(args: dict[str, Any]) -> int:
    value = args.get("timeout_s", 120)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 600:
        raise ValueError("timeout_s must be an integer from 1 through 600")
    return value


def _confirm(args: dict[str, Any]) -> None:
    if args.get("confirm") is not True:
        raise ValueError("This operation mutates or approves state; pass confirm=true explicitly")


def no_mistakes_admin(args: dict[str, Any], **kw) -> str:
    """Run a supported root no-mistakes command."""
    operation = args.get("operation")
    if operation not in _ROOT_READ | _ROOT_MUTATE:
        return json.dumps({"ok": False, "error": f"unsupported operation: {operation!r}"})
    if operation in _ROOT_MUTATE:
        _confirm(args)
    argv = [operation]
    if operation == "init":
        fork_url = args.get("fork_url")
        if not isinstance(fork_url, str) or not fork_url.strip():
            raise ValueError("init requires a non-empty fork_url")
        argv += ["--fork-url", fork_url]
    return _result(argv, _workdir(args, kw), _timeout(args))


def no_mistakes_axi(args: dict[str, Any], **kw) -> str:
    """Run one supported non-interactive no-mistakes AXI operation."""
    operation = args.get("operation")
    if operation not in _AXI_READ | _AXI_MUTATE:
        return json.dumps({"ok": False, "error": f"unsupported operation: {operation!r}"})
    if operation in _AXI_MUTATE:
        _confirm(args)
    argv = ["axi", operation]
    if operation == "run":
        intent = args.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            raise ValueError("axi run requires a non-empty intent")
        argv += ["--intent", intent]
    elif operation == "respond":
        action = args.get("action")
        if action not in {"approve", "fix", "skip"}:
            raise ValueError("axi respond action must be approve, fix, or skip")
        argv += ["--action", action]
        findings = args.get("findings", [])
        if findings:
            if not isinstance(findings, list) or not all(isinstance(item, str) and item for item in findings):
                raise ValueError("findings must be a list of non-empty strings")
            argv += ["--findings", ",".join(findings)]
    elif operation == "logs":
        step = args.get("step")
        if not isinstance(step, str) or not step.strip():
            raise ValueError("axi logs requires a step")
        argv += ["--step", step, "--full"]
    elif operation == "status" and args.get("run"):
        argv += ["--run", str(args["run"])]
    return _result(argv, _workdir(args, kw), _timeout(args))


def _schema(description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": "no_mistakes",
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


ADMIN_SCHEMA = _schema(
    "Operate the local no-mistakes CLI. Read-only operations are status, doctor, and runs. Mutating operations require confirm=true. Interactive attach is intentionally terminal-only.",
    {
        "operation": {"type": "string", "enum": sorted(_ROOT_READ | _ROOT_MUTATE)},
        "fork_url": {"type": "string", "description": "HTTPS fork URL for init."},
        "confirm": {"type": "boolean", "description": "Required true for init, rerun, update, eject, or sync."},
        "workdir": {"type": "string", "description": "Absolute repository worktree path."},
        "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600},
    },
    ["operation"],
)

AXI_SCHEMA = _schema(
    "Operate the complete non-interactive no-mistakes AXI interface. Read-only operations are status and logs. run, respond, abort, and sync require confirm=true; run also requires intent and respond requires action.",
    {
        "operation": {"type": "string", "enum": sorted(_AXI_READ | _AXI_MUTATE)},
        "intent": {"type": "string", "description": "Required for axi run."},
        "action": {"type": "string", "enum": ["approve", "fix", "skip"], "description": "Required for axi respond."},
        "findings": {"type": "array", "items": {"type": "string"}, "description": "Finding IDs for axi respond --action fix."},
        "step": {"type": "string", "description": "Required for axi logs."},
        "run": {"type": "string", "description": "Optional run ID for axi status."},
        "confirm": {"type": "boolean", "description": "Required true for run, respond, abort, or sync."},
        "workdir": {"type": "string", "description": "Absolute repository worktree path."},
        "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600},
    },
    ["operation"],
)


def register_tools(ctx) -> None:
    ctx.register_tool(name="no_mistakes_admin", toolset="no_mistakes", schema=ADMIN_SCHEMA, handler=no_mistakes_admin)
    ctx.register_tool(name="no_mistakes_axi", toolset="no_mistakes", schema=AXI_SCHEMA, handler=no_mistakes_axi)
