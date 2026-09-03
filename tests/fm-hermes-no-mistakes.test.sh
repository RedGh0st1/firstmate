#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$ROOT/.hermes/plugins${PYTHONPATH:+:$PYTHONPATH}"

python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = sys.argv[1]
from firstmate.no_mistakes import no_mistakes_admin, no_mistakes_axi

for label, result in (
    ("admin_status", no_mistakes_admin({"operation": "status", "workdir": root})),
    ("axi_status", no_mistakes_axi({"operation": "status", "workdir": root})),
):
    data = json.loads(result)
    assert data["ok"] is True, (label, data)
    assert data["exit_code"] == 0, (label, data)
    print(f"ok - {label} real CLI dispatch")

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
PY
