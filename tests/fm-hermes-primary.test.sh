#!/usr/bin/env bash
# Regression coverage for the Hermes primary adapter registration and plugin.
set -u

# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

CONTROL="$ROOT/bin/fm-control-lib.sh"
HARNESS="$ROOT/bin/fm-harness.sh"
PLUGIN="$ROOT/.hermes/plugins/firstmate/__init__.py"

assert_eq() {
  local expected=$1 actual=$2 message=$3
  [ "$actual" = "$expected" ] || fail "$message: expected '$expected', got '$actual'"
}

test_harness_marker_detects_hermes() {
  assert_eq hermes "$(HERMES_AGENT=true "$HARNESS")" "Hermes marker detection"
  pass "fm-harness detects HERMES_AGENT=true as hermes"
}

test_harness_marker_hermes_wins_over_foreign_markers() {
  local got
  got=$(CLAUDECODE=1 PI_CODING_AGENT=true GROK_AGENT=1 HERMES_AGENT=true "$HARNESS")
  assert_eq hermes "$got" "Hermes marker precedence over inherited claude/pi/grok markers"
  pass "fm-harness prefers HERMES_AGENT over an inherited foreign primary marker"
}

test_control_table_supports_hermes() {
  # shellcheck source=/dev/null
  . "$CONTROL"
  fm_control_harness_supported hermes || fail "Hermes is not a supported control harness"
  assert_eq hermes "$(fm_control_harness_family hermes)" "Hermes family"
  assert_eq Escape "$(fm_control_interrupt_key hermes)" "Hermes interrupt key"
  assert_eq 1 "$(fm_control_interrupt_repeat hermes)" "Hermes interrupt repeat"
  assert_eq /exit "$(fm_control_exit_command hermes)" "Hermes exit command"
  pass "control table exposes Hermes lifecycle operations"
}

test_hermes_plugin_compiles() {
  python3 -m py_compile "$PLUGIN" || fail "Hermes project plugin does not compile"
  pass "Hermes project plugin compiles"
}

test_hermes_plugin_guard_injects_bounded_followup() {
  local tmp
  tmp=$(fm_test_tmproot fm-hermes-plugin) || fail "could not create plugin test root"
  mkdir -p "$tmp/bin"
  : > "$tmp/AGENTS.md"

  cat > "$tmp/bin/fm-watch-arm.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
  cat > "$tmp/bin/fm-turnend-guard.sh" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
exit 2
SH
  cat > "$tmp/bin/fm-supervision-instructions.sh" <<'SH'
#!/usr/bin/env bash
printf 'REPAIR: inspect the Hermes project plugin\n'
SH
  cat > "$tmp/bin/fm-operational-input.sh" <<'SH'
#!/usr/bin/env bash
[ "$1" = encode ] && [ "$2" = turn-end-guard ] || { echo "unexpected encode args" >&2; exit 3; }
printf 'ENCODED[%s]\n' "$(cat)"
SH
  chmod +x "$tmp"/bin/*.sh

  DRIVER_ROOT="$tmp" PLUGIN_PATH="$PLUGIN" python3 - <<'PY' || fail "Hermes plugin behavioral checks failed"
import importlib.util
import os
from pathlib import Path

root = Path(os.environ["DRIVER_ROOT"])
spec = importlib.util.spec_from_file_location("firstmate_hermes_under_test", os.environ["PLUGIN_PATH"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Ctx:
    def __init__(self):
        self.hooks = {}
        self.messages = []

    def register_hook(self, name, fn):
        self.hooks.setdefault(name, []).append(fn)

    def inject_message(self, message, role=None):
        self.messages.append((message, role))


# A checkout without the Firstmate markers registers nothing.
mod._root = lambda: root / "absent"
bare = Ctx()
mod.register(bare)
assert bare.hooks == {}, bare.hooks

mod._root = lambda: root
ctx = Ctx()
mod.register(ctx)
for name in ("on_stream_start", "on_session_start", "on_session_end"):
    assert name in ctx.hooks, ctx.hooks

on_session_end = ctx.hooks["on_session_end"][0]
on_stream_start = ctx.hooks["on_stream_start"][0]

on_session_end()
assert len(ctx.messages) == 1, ctx.messages
message, role = ctx.messages[0]
assert role == "user", role
assert message.startswith("ENCODED["), message
assert "REPAIR: inspect the Hermes project plugin" in message, message

# The latch holds a second turn end until a new stream starts.
on_session_end()
assert len(ctx.messages) == 1, ctx.messages

on_stream_start()
on_session_end()
assert len(ctx.messages) == 2, ctx.messages
PY
  pass "Hermes plugin injects exactly one bounded follow-up per stream on a guard lapse"
}

test_harness_marker_detects_hermes
test_harness_marker_hermes_wins_over_foreign_markers
test_control_table_supports_hermes
test_hermes_plugin_compiles
test_hermes_plugin_guard_injects_bounded_followup
