#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$ROOT/.hermes/plugins${PYTHONPATH:+:$PYTHONPATH}"

python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = sys.argv[1]
from firstmate import no_mistakes as nm
from firstmate.no_mistakes import no_mistakes_admin, no_mistakes_axi

# Both controls shell out to the real `no-mistakes` binary and return a
# structured envelope. `no-mistakes status` exits 0 even in a checkout that has
# not been `no-mistakes init`-ed; `no-mistakes axi status` exits non-zero there.
# When this suite runs inside an isolated no-mistakes gate worktree (rather than
# a registered developer checkout) the repo is legitimately "not initialized",
# so tolerate exactly that well-defined failure mode while still proving the
# dispatch contract (argv, no hang, verbatim CLI output).
for label, result, argv in (
    ("admin_status", no_mistakes_admin({"operation": "status", "workdir": root}), ["status"]),
    ("axi_status", no_mistakes_axi({"operation": "status", "workdir": root}), ["axi", "status"]),
):
    data = json.loads(result)
    assert data["argv_redacted"] == argv, (label, data)
    assert data["timed_out"] is False, (label, data)
    assert "exit_code" in data, (label, data)
    initialized = data["ok"] is True
    if initialized:
        assert data["exit_code"] == 0, (label, data)
    else:
        assert "not initialized" in data["stdout"], (label, data)
    print(f"ok - {label} real CLI dispatch ({'initialized repo' if initialized else 'graceful not-initialized failure'})")

try:
    no_mistakes_axi({"operation": "sync", "workdir": root})
except ValueError:
    print("ok - mutation requires explicit confirmation")
else:
    raise AssertionError("mutation without confirmation was accepted")

try:
    no_mistakes_axi({"operation": "run", "confirm": True, "workdir": root})
except ValueError:
    print("ok - AXI run requires intent")
else:
    raise AssertionError("AXI run without intent was accepted")

# `axi respond --action approve` is an approval action and must stay gated.
try:
    no_mistakes_axi({"operation": "respond", "action": "approve", "workdir": root})
except ValueError:
    print("ok - AXI respond approve requires explicit confirmation")
else:
    raise AssertionError("AXI respond approve without confirmation was accepted")

# `axi logs` forwards --run so a Hermes operator can pull logs for any run, not
# just the current one (review-round capability).
captured = {}
real_result = nm._result
nm._result = lambda a, cwd, timeout_s: captured.setdefault("argv", list(a)) or "{}"
try:
    no_mistakes_axi({"operation": "logs", "step": "ci", "run": "01RUNIDEXAMPLE0000000000000", "workdir": root})
finally:
    nm._result = real_result
assert captured["argv"] == ["axi", "logs", "--step", "ci", "--full", "--run", "01RUNIDEXAMPLE0000000000000"], captured
print("ok - AXI logs forwards --run passthrough")

# Redaction covers the widened GitHub token prefixes (review-round fix).
for prefix in ("gho_", "ghp_", "ghu_", "ghs_", "ghr_", "github_pat_"):
    sample = f"leaked {prefix}DEADbeef0123456789abcdef here"
    redacted = nm._redact(sample)
    assert prefix + "DEAD" not in redacted and "[REDACTED]" in redacted, (prefix, redacted)
print("ok - secret redaction covers ghp_/ghu_/ghs_/ghr_/gho_/github_pat_")
PY
