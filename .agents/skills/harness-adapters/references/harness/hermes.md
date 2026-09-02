# Hermes

Hermes primary integration is supported on Hermes Agent 0.20.6 or newer.
The adapter was initially exercised on the Mac mini with Hermes Agent v0.20.6.

## Operating facts

| Fact | Value |
|---|---|
| Binary | `hermes` resolved from PATH. |
| Marker | Hermes sets `HERMES_AGENT=true` for the interactive process and its tool children. |
| Launch | `HERMES_ENABLE_PROJECT_PLUGINS=true hermes --accept-hooks`; `--yolo` is added for unattended worker launches. |
| Busy state | The project plugin owns the Hermes session boundary and uses the shared watcher and guard state; it does not infer busy state from rendered terminal text. |
| Exit | `/exit`. |
| Interrupt | Single Escape. |
| Skill invocation | `/` followed by the skill name. |
| Resume | `hermes --continue` or `hermes --resume <session>`. |
| Model | `--model <provider/model>`. |
| Effort | No Firstmate effort flag is passed because Hermes effort support is profile and provider dependent. |

## Primary integration

The project-local plugin at `.hermes/plugins/firstmate/` registers `on_session_start`, `on_stream_start`, and `on_session_end` hooks.
Hermes project plugins are disabled by default, so the documented launch command explicitly sets `HERMES_ENABLE_PROJECT_PLUGINS=true`.

At session start the plugin starts one detached `bin/fm-watch-arm.sh` process with `FM_ROOT_OVERRIDE` and `FM_HOME` bound to the Firstmate checkout.
At session end it re-arms the watcher, invokes `bin/fm-turnend-guard.sh`, and queues at most one typed `turn-end-guard` follow-up with `ctx.inject_message()` when the guard returns 2.
The follow-up latch resets when the next Hermes stream starts.

Hermes hook callbacks are observer hooks and cannot block the host turn boundary.
The Hermes adapter therefore uses the passive bounded-follow-up path, preserving the shared guard predicate and never silently treating an unverified watcher as healthy.

## Installation and trust

Start Hermes from the Firstmate repository root:

```sh
HERMES_ENABLE_PROJECT_PLUGINS=true hermes --accept-hooks
```

For a Firstmate-launched worker, `bin/fm-spawn.sh` supplies the same project-plugin opt-in and `--accept-hooks` flag.
Do not enable the plugin globally when operating outside a Firstmate checkout.

The plugin runs local Firstmate scripts only when the checkout contains both `AGENTS.md` and `bin/fm-watch-arm.sh`.
Its callback errors are logged by Hermes and never replace the shared fail-closed guard logic.

## Verification boundary

Run the deterministic adapter tests before trusting the integration.
A live Hermes smoke test must use the installed Hermes binary and record its version, plugin load result, watcher arm result, and one bounded guard follow-up.
Headless `hermes chat -q` is not a primary session and is outside this adapter's turn-end supervision boundary.
