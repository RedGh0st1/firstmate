# Hermes no-mistakes and AXI integration

This follow-up extends the Firstmate Hermes native plugin with the local no-mistakes and AXI control surfaces.

## Exposed Hermes tools

`no_mistakes_admin` exposes the non-interactive root commands:

- Read-only: `status`, `doctor`, `runs`
- Confirmation required: `init`, `rerun`, `update`, `eject`, `sync`

`no_mistakes_axi` exposes the complete non-interactive AXI commands:

- Read-only: `status`, `logs`
- Confirmation required: `run`, `respond`, `abort`, `sync`

`axi run` requires an explicit `intent`. `axi respond` accepts only `approve`, `fix`, or `skip` and requires explicit confirmation. Interactive `attach` remains terminal-only.

## Safety contract

- Every invocation uses a fixed executable plus an argv list; no shell interpolation is used.
- Workdir is explicit when supplied and otherwise comes from the Hermes session/process context.
- Results include sanitized argv, cwd, stdout, stderr, exit code, timeout state, and parsed JSON when available.
- Credentials and token-like values are redacted from returned output.
- These tools expose no Factory evidence-writing operation. Gate-mutating AXI actions (`respond`, including `--action approve`, plus `abort` and `sync`) are reachable only with an explicit per-call `confirm=true`, never through an implicit, default, or batched path.
- Native plugin load and callback failures remain Hermes fail-open boundaries; no tool claims stronger enforcement.

## AI-OS use

The canonical AI-OS policy remains authoritative for dispatch, human approval, security review, independent verification, and merge authority. Hermes is the sole dispatcher. Use the tools for inspection and for explicitly confirmed no-mistakes operations; gate approval through `axi respond --action approve` is reachable but demands a deliberate per-call `confirm=true`, Factory control-plane evidence is never written through these tools, and interactive `attach` stays in the human-operated terminal path.

To make the project plugin available in a Hermes session from this repository:

```sh
cd /Users/lennienurse/ai-repos/firstmate
HERMES_ENABLE_PROJECT_PLUGINS=1 hermes
```

For a global Hermes installation after this PR is reviewed and merged, install the released plugin package through Hermes' plugin installer or copy the reviewed directory to the profile's `$HERMES_HOME/plugins/` location. Verify with:

```sh
hermes plugins doctor /path/to/firstmate/.hermes/plugins/firstmate --ci
hermes plugins list --plain --no-bundled
```

The live Hermes profile and AI-OS resident configuration must be changed only after human review of the final merged plugin and its capability report.
