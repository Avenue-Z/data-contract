# Event-log reader (`contract events`) — Design

**Date:** 2026-07-24
**Status:** Draft — under review
**Owner:** Paul Ramirez / Engineering
**Implements:** system design §4.4 (validation event log), §5.4 (CLI); closes the §15 item-5
residual "the event log still has no reader."

## 1. Purpose

The adoption on-ramp the authoring skill teaches (v0.2.0+, and now the §5.5 skill) is
**"adopt in `observe` → read the event log → promote to `enforce`."** Today that middle step
resolves to "parse the JSONL yourself." `EventLog` (`events.py`) exposes `emit()` and a public
`records()` — but `records()` is a method on the **unexported** `EventLog` class (not part of R9's
frozen surface), so a consumer cannot reach it through the supported API, and it is **not tolerant**:
it calls `json.loads(line)` on every non-blank line (`events.py:30`) and therefore crashes on exactly
the truncated final line a crashed-mid-write log is most likely to have. So this feature builds a new
tolerant reader rather than reusing `records()`. `contract events` gives the author (and consuming
agents) a first-class, opinionated read of **"has this boundary shown any violation that would
hard-fail under `enforce`?"**

## 2. Shape

A new CLI command `contract events`, wrapping two functions in
`src/contract_core/events_report.py`, split so each is independently unit-testable (the §11 pure-
function philosophy used for reconcile/compat):

- `read_records(path) -> tuple[list[dict], int]` — the **tolerant reader**. Reads the JSONL and
  returns `(records, n_skipped)`, skipping any blank or un-parseable line (the truncated final line)
  and counting it. This is the *only* function that sees raw lines, so it is where the truncated-line
  case is tested. It is not pure (it does file I/O) but is deterministic and unit-tested against
  temp files, exactly as the reconcile suite tests its scanners.
- `summarize(records, *, contract=None, skipped=0) -> Report` — the **pure** core: parsed records in,
  a `Report` out, no I/O. `skipped` is threaded in so it reaches the `Report.summary` (and therefore
  both the human and `--json` output — see §4). Testable with in-memory dicts, no disk.

`cli.py` owns the orchestration: resolve the log path, call `read_records`, optionally load the
contract, call `summarize`, render. The public Python API stays **frozen** (R9's six names); this is
CLI-only — `read_records`, `summarize`, and `EventLog.records()` are all private. Run it through the
`contract` console script.

### Inputs

| Flag | Required | Default | Purpose |
| --- | --- | --- | --- |
| `--log <path>` | no | `$CONTRACT_EVENT_LOG`, else `./contract-events.jsonl` | the JSONL to read (same resolution `EventLog` uses) |
| `--contract <path>` | no | — | when given, flags declared-but-never-observed boundaries |
| `--json` | no | off | structured output for consuming agents |

## 3. The verdict (the opinionated core)

**Grouping key: `(system, boundary, schema, version)`.** One row per observed boundary-at-a-ref.
This is deliberate: it *never* silently merges event counts across two different schemas. If a
boundary is observed under two refs in one log (the contract was edited mid-observe), it appears as
two rows — honest, not merged. Per group: event count, pass/warn/violation counts, and the last
observed shape (see §4 for what "last" means).

| Verdict | Condition | On-ramp meaning (a sampling signal, not a guarantee) |
| --- | --- | --- |
| `clean` | ≥1 event, all `pass` | **No violations observed** in the traffic that ran — the evidence supports promoting to `enforce`, up to what was exercised. |
| `review` | ≥1 `warn`, no `violation` | No violations observed; a `warn` won't hard-fail under `enforce` (it is the non-blocking output extra-field case). Reconcile the warns, then promote. |
| `blocked` | any `violation` | A `violation` was observed under `observe`, and **the same input would hard-fail under `enforce`**. Do not promote. |
| `unobserved` | declared in `--contract` but 0 events | Never exercised — no evidence either way; not safe to enforce yet. |

Every verdict is a statement about **observed traffic**, not a proof about all future data — the
tool is a confidence heuristic for the on-ramp, and the wording says so.

**Why the warn/violation split is trustworthy (cite, don't assume).** The whole safety argument
rests on one runtime invariant: `result="violation"` is emitted for *any* hard diff
(missing/retyped/nullable/value) **regardless of mode**, and `result="warn"` *only* for the
non-blocking output-extra-field case; the actual hard-fail is separately gated on `mode == "enforce"`
(`runtime.py:149-166`). That is precisely why a `violation` seen under `observe` predicts a hard-fail
under `enforce`, and a `warn` does not. If a future runtime change ever emitted `warn` for a
different case, this tool's `clean`/`review` verdicts would quietly become wrong — so the invariant
is cited here as a contract, and a `summarize` unit test pins the mapping.

**Accepted limitation — no `direction` in the record.** The registry keys boundaries by
`(system, direction, name)` (`runtime.py:74`), but `emit()` writes only `boundary=spec.name`, with no
`direction` (`runtime.py:161`). §7 forbids changing the emitted record format, so this reader cannot
recover direction. Consequence: a contract that reuses one `name` across two directions (e.g. a `raw`
and an `input` both named `x`) **and** points both at the same `schema@version` collapses into a
single group. Distinct schemas (the normal case — a raw per-call-site shape differs from the
normalized input) already split via the key. This residual is documented, not silently merged.

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

Each row is one observed `(boundary, schema@version)` group (§3), sorted worst-first. "Last observed
shape" is the shape from the **last matching line in file order** — the JSONL is append-only, so file
order is arrival order; record timestamps normally agree but file order is the definition, so no
sort-by-timestamp is implied. When `read_records` skips a truncated/blank line, a trailing note
appears: `(1 malformed line skipped)`.

`--json` emits the same content as a structured object:
`{systems: [{system, boundaries: [{boundary, schema, version, events, pass, warn, violation,
last_shape, verdict}], unobserved: [{boundary, schema, version}]}], summary: {clean, review, blocked,
unobserved, skipped, ready: bool}}`. `skipped` is in the summary so the machine consumer — the whole
audience `--json` exists for — can tell that N records were discarded; omitting it would be silent
data loss for the reader whose entire job is confidence. A log spanning multiple systems yields one
entry per system under `systems`.

### Exit code

`contract events` is a **reporting tool, not a gate** — the mode ladder and `reconcile` are the
gates. It exits **0** on any successful read (even when boundaries are `blocked` — that is a finding
to report, not a tool error), and non-zero only on a real error:

- a malformed `--contract` (`ContractFormatError`, rendered like `lint`);
- an unreadable `--log` **path that exists** — a directory, or permission-denied — which raises
  `OSError`; caught and reported cleanly (mirroring `lint`'s `OSError` arm at `cli.py:70`), not left
  to traceback.

A **missing** log is not an error (→ §5, exit 0). A truncated final JSONL line inside a readable log
is tolerated by `read_records`, not an error.

## 5. Edge cases

- **Empty or missing log** → `read_records` returns `([], 0)` for a non-existent path (mirroring
  `records()`'s `is_file()` guard); `cli.py` renders "no events recorded" + a hint (observe hasn't
  run, or `--log` is wrong) whenever the record list is empty; exit 0.
- **Present-but-unreadable log** (a directory, or permission-denied) → `read_records` does *not*
  swallow this: the path exists, so it attempts the read and lets `OSError`
  (`IsADirectoryError`/`PermissionError`) propagate; `cli.py` catches and reports it, exit non-zero
  (§4). The missing-vs-unreadable split is `path.exists()`: absent → `([], 0)`, present → read.
- **Malformed / truncated JSONL line** → `read_records` skips and counts it; the count reaches the
  `Report.summary.skipped` and both outputs (§4).
- **Observed shape rendering** → tabular `{columns, dtypes}` shows `cols=[...]`; payload `{keys}`
  shows `keys=[...]`. `--json` passes `observed_shape` through unchanged as `last_shape`.
- **schema@version drift within a log** (the contract was edited mid-observe) → **two rows**, one per
  ref, via the grouping key (§3). No merge, no "latest wins."

## 6. Testing (TDD)

- `tests/test_events_report.py` — `read_records` over temp files: a clean log, a **truncated final
  line** (skipped, `n_skipped == 1`), a blank-line-only file, a missing file. `summarize` over
  in-memory records (pure): every verdict (`clean`/`review`/`blocked`), the `warn`-vs-`violation`
  mapping pinned against the `runtime.py` invariant (§3), the `unobserved` path (with a `Contract`),
  the drift-into-two-rows case, multi-system logs, and `skipped` reaching `summary`.
- `tests/test_cli.py` — the `events` command end to end: flag wiring, `--json` shape (including
  `summary.skipped`), the missing-log hint (exit 0), the unreadable-`--log` `OSError` (exit non-zero),
  and a malformed `--contract` (exit non-zero).

## 7. Version & scope

- Additive CLI command → **0.6.0**; CHANGELOG entry.
- Not built (YAGNI): a `--strict` exit-non-zero gate mode (the gates already exist); time-range
  filtering; per-record raw dump (a separate `--raw` view can be added later if a forensic need
  appears — this design is the readiness summary only).
- No change to `EventLog`, the emitted record format, or the public API.
