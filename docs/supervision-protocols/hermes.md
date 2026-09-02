Mode: Hermes project-plugin supervision with bounded follow-up.

When this session owns supervision and away mode is not active:
1. Drain first with `bin/fm-wake-drain.sh`.
   After handling all emitted wakes and reconciling open decisions and unread status lines, run the exact `--ack-through` command printed as `WAKE_ACK_REQUIRED`.
2. Start Hermes from the Firstmate repository root with `HERMES_ENABLE_PROJECT_PLUGINS=true hermes --accept-hooks`.
3. The project plugin starts one detached `bin/fm-watch-arm.sh` cycle on session start, re-arms a successor cycle after each cycle exit (bounded exponential retry on a failed exit), and also re-arms at session end.
   On an actionable cycle close it injects the typed `watcher` wake with a drain directive through Hermes `ctx.inject_message()`.
4. The plugin invokes `bin/fm-turnend-guard.sh` at session end.
   When the guard returns 2, it injects at most one typed `turn-end-guard` follow-up through Hermes `ctx.inject_message()`.
5. Ordinary wake: run `bin/fm-wake-drain.sh`, handle the reported wake, and do not manually start another watcher cycle while the plugin is enabled.
6. If the plugin exhausts its bounded re-arm retries it injects a typed `FAILED` watcher notice; inspect the failure and use the repair line below rather than creating a second watcher.
7. Hermes hooks cannot block the host turn boundary, so this is a passive adapter with a bounded follow-up and a fail-open hook boundary.
8. Never use shell `&` for watcher supervision.

The plugin is active only from a Firstmate-shaped checkout containing `AGENTS.md` and `bin/fm-watch-arm.sh`.
The watcher remains home-scoped through `FM_ROOT_OVERRIDE` and `FM_HOME`.
