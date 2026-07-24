# Event-log reader (`contract events`) — Design

**Date:** 2026-07-24
**Status:** Approved for build (TDD)
**Owner:** Paul Ramirez / Engineering
**Implements:** system design §4.4 (validation event log), §5.4 (CLI); closes the §15 item-5
residual "the event log still has no reader."

## 1. Purpose

The adoption on-ramp the authoring skill teaches (v0.2.0+, and now the §5.5 skill) is
**"adopt in `observe` → read the event log → promote to `enforce`."** Today that middle step
resolves to "parse the JSONL yourself" — `EventLog` has `emit()` and a private `records()`, no
first-class reader. This makes the on-ramp's confidence step manual, which is exactly the friction
R7 is measured against. `contract events` gives the author (and consuming agents) a first-class,
opinionated answer to **"is this boundary safe to promote to `enforce`?"**

## 2. Shape

A new CLI command `contract events`, wrapping a **pure summarizer** (`records in → report out`,
no I/O), matching the §11 testing philosophy already used for reconcile/compat (pure function →
unit-tested, no fixtures-on-disk needed).

- The pure core lives in `src/contract_core/events_report.py`: `summarize(records, contract=None)
  -> Report`.
- `cli.py` owns the I/O (read the JSONL, optionally load the contract) and rendering.
- The public Python API stays **frozen** (R9's six names). This is CLI-only; `records()` and the
  new summarizer stay private. Run it through the `contract` console script.

### Inputs

| Flag | Required | Default | Purpose |
| --- | --- | --- | --- |
| `--log <path>` | no | `$CONTRACT_EVENT_LOG`, else `./contract-events.jsonl` | the JSONL to read (same resolution `EventLog` uses) |
| `--contract <path>` | no | — | when given, flags declared-but-never-observed boundaries |
| `--json` | no | off | structured output for consuming agents |

## 3. The verdict (the opinionated core)

Group events by `(system, boundary)`. Per group: the observed `schema@version`, event count,
pass/warn/violation counts, and the **last** observed shape. Verdict:

| Verdict | Condition | On-ramp meaning |
| --- | --- | --- |
| `clean` | ≥1 event, all `pass` | Safe to promote to `enforce`. |
| `review` | ≥1 `warn`, no `violation` | Safe to enforce (a `warn` is the non-blocking output extra-field, §5.2), but reconcile the warns first. |
| `blocked` | any `violation` | A `violation` observed under `observe` **would hard-fail under `enforce`**. Do not promote. |
| `unobserved` | declared in `--contract` but 0 events | Never exercised — cannot judge; not safe to enforce yet. |

`unobserved` requires `--contract`; without it, a declared-but-unfired boundary simply does not
appear. Observed-but-undeclared boundaries are **not** this tool's job — `reconcile` owns that diff.

## 4. Output

Human default, sorted worst-first (`blocked` → `unobserved` → `review` → `clean`), plain-text tags
(no glyphs, terminal-safe), the existing CLI's `—` house style:

```
demo-consumer — 3 boundaries
  [blocked]    prompts        peec.prompts_export@1   12 events  (9 pass, 0 warn, 3 violation)
                 last shape: cols=[prompt, sentiment, position] — 3 violations would hard-fail under enforce
  [review]     report         aivx.report@1            8 events  (7 pass, 1 warn, 0 violation)
  [clean]      prompts_raw    peec.prompts_raw@1      12 events
  [unobserved] team_capacity  (declared, never observed)

Not ready: 1 blocked, 1 unobserved. 1 clean, 1 needs review.
```

`--json` emits the same content as a structured object:
`{system, boundaries: [{boundary, schema, version, events, pass, warn, violation, last_shape,
verdict}], unobserved: [{boundary, schema, version}], summary: {clean, review, blocked, unobserved,
ready: bool}}`. A log spanning multiple systems yields one block/object per system.

### Exit code

`contract events` is a **reporting tool, not a gate** — the mode ladder and `reconcile` are the
gates. It exits **0** on any successful read (even when boundaries are `blocked` — that is a finding
to report, not a tool error), and non-zero only on a real error: an unreadable/malformed contract
(`ContractFormatError`, rendered like `lint`). A truncated final JSONL line (a crash mid-write) is
**tolerated** — the reader skips it and notes the count, rather than crashing on the one thing an
event log is most likely to have.

## 5. Edge cases

- **Empty or missing log** → "no events recorded" + a hint (observe hasn't run, or `--log` is
  wrong); exit 0.
- **Malformed JSONL line** → skipped and counted (`"1 malformed line skipped"`); the rest summarize.
- **Observed shape rendering** → tabular `{columns, dtypes}` shows `cols=[...]`; payload `{keys}`
  shows `keys=[...]`. `--json` passes `observed_shape` through unchanged.
- **schema@version drift within a log** (the contract was edited mid-observe) → report the latest
  observed ref and note the change; do not merge counts across refs silently.

## 6. Testing (TDD)

The summarizer is a pure function → `tests/test_events_report.py` covers every verdict, the
`unobserved` path (with a contract), empty/missing log, a truncated line, multi-system logs, and
schema-drift-within-a-log. CLI-level tests in `tests/test_cli.py` cover flag wiring, `--json`
shape, and exit codes.

## 7. Version & scope

- Additive CLI command → **0.6.0**; CHANGELOG entry.
- Not built (YAGNI): a `--strict` exit-non-zero gate mode (the gates already exist); time-range
  filtering; per-record raw dump (a separate `--raw` view can be added later if a forensic need
  appears — this design is the readiness summary only).
- No change to `EventLog`, the emitted record format, or the public API.
