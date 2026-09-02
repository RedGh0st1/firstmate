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

test_harness_marker_detects_hermes
test_control_table_supports_hermes
test_hermes_plugin_compiles
