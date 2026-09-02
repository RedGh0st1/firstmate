"""End-to-end drive of the real Hermes primary plugin hooks.

Loads .hermes/plugins/firstmate/__init__.py unmodified and exercises the
observable behaviour an operator depends on:

  scenario "wake"   - an actionable watcher cycle-close is delivered as a typed
                      `watcher` operational-input wake with the drain directive,
                      and the plugin re-arms a successor watch cycle.
  scenario "failed" - repeated arm failures are bounded, and once the retry
                      budget is exhausted the plugin injects a distinct typed
                      FAILED notice instead of spinning forever.

Run:  python3 hermes_watcher_e2e.py <repo-root> <scenario>
"""

import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
SCENARIO = sys.argv[2]

work = Path(tempfile.mkdtemp(prefix="hermes-e2e-"))
(work / "AGENTS.md").write_text("")
bindir = work / "bin"
bindir.mkdir()
counter = work / "arm-invocations"
counter.write_text("")

# Real encoder + repair-line renderer from the checkout under test.
for name in ("fm-operational-input.sh", "fm-supervision-instructions.sh",
             "fm-turnend-guard.sh"):
    src = REPO / "bin" / name
    (bindir / name).symlink_to(src)

if SCENARIO == "wake":
    (bindir / "fm-watch-arm.sh").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> "{counter}"\n'
        'echo "signal: captain flagged a blocked crewmate"\n'
        'exit 0\n'
    )
    retry_limit = "5"
else:  # failed
    (bindir / "fm-watch-arm.sh").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> "{counter}"\n'
        'echo "watcher: FAILED - no live watcher with a fresh beacon" >&2\n'
        'exit 1\n'
    )
    retry_limit = "2"
os.chmod(bindir / "fm-watch-arm.sh", 0o755)

os.environ["FM_WATCH_REARM_RETRY_LIMIT"] = retry_limit
os.environ["FM_WATCH_REARM_RETRY_BASE_MS"] = "50"
os.environ["FM_WATCH_REARM_RETRY_MAX_MS"] = "120"

spec = importlib.util.spec_from_file_location(
    "firstmate_hermes_e2e", REPO / ".hermes" / "plugins" / "firstmate" / "__init__.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod._root = lambda: work


class Ctx:
    def __init__(self):
        self.hooks = {}
        self.messages = []

    def register_hook(self, name, fn):
        self.hooks.setdefault(name, []).append(fn)

    def inject_message(self, message, role=None):
        self.messages.append((role, message))


ctx = Ctx()
mod.register(ctx)
print("registered hooks:", sorted(ctx.hooks))

# on_session_start arms the first watch cycle.
ctx.hooks["on_session_start"][0]()

deadline = time.time() + 8
while time.time() < deadline:
    arms = [x for x in counter.read_text().splitlines() if x]
    if SCENARIO == "wake" and ctx.messages and len(arms) >= 2:
        break
    if SCENARIO == "failed" and any("FAILED" in m for _, m in ctx.messages):
        break
    time.sleep(0.1)

mod._disarm()
time.sleep(0.2)

arms = [x for x in counter.read_text().splitlines() if x]
print(f"\nscenario={SCENARIO}")
print(f"fm-watch-arm.sh invocations (distinct pids): {len(arms)}")
print("injected messages:")
for role, m in ctx.messages:
    print(f"  role={role!r}  {m!r}")

failures = []
if SCENARIO == "wake":
    if len(arms) < 2:
        failures.append("expected the plugin to re-arm a successor cycle (>=2 invocations)")
    if not ctx.messages:
        failures.append("expected one typed watcher wake to be injected")
    else:
        role, msg = ctx.messages[0]
        if role != "user":
            failures.append(f"wake role should be 'user', got {role!r}")
        if "FIRSTMATE_OP: v1 watcher:" not in msg:
            failures.append("wake was not encoded as a typed 'watcher' operational input")
        if "bin/fm-wake-drain.sh" not in msg:
            failures.append("wake is missing the drain directive")
        if "signal: captain flagged a blocked crewmate" not in msg:
            failures.append("wake did not carry the actionable cycle-close line")
else:
    if not (retry_limit_int := int(retry_limit)) or len(arms) > retry_limit_int + 2:
        failures.append(f"re-arm was not bounded: {len(arms)} invocations for limit {retry_limit}")
    failed_msgs = [m for _, m in ctx.messages if "FIRSTMATE WATCHER FAILED" in m]
    if not failed_msgs:
        failures.append("expected a distinct typed FAILED watcher notice after the retry budget")
    else:
        if "FIRSTMATE_OP: v1 watcher:" not in failed_msgs[0]:
            failures.append("FAILED notice was not encoded as a typed 'watcher' operational input")
        if "supervision is down" not in failed_msgs[0]:
            failures.append("FAILED notice does not state supervision is down")
        if "WATCHER FIRED" in failed_msgs[0]:
            failures.append("FAILED notice wrongly reused the ordinary wake preamble")

print("\nRESULT:", "PASS" if not failures else "FAIL")
for f in failures:
    print("  -", f)
sys.exit(1 if failures else 0)
