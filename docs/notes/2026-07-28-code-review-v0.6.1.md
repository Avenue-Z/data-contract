# contract-core v0.6.1 — code review

Full-library review of the merged code at `0.6.1` (dev == main, tree-identical). Reviewer: Thomas.
Documentation only: this file changes no code. Every finding below lists a fix as a follow-up for the
author to action; nothing here edits the reviewed branch.

## What was verified

The whole library was read end to end, and the review ran the code rather than trusting it:

- `pytest` — **295 passed**
- `mypy --strict` — **clean** (17 source files)
- `ruff check` — **clean**
- Version parity: `__init__.__version__`, `pyproject`, and the released tag all agree at `0.6.1`.

Every finding marked **reproduced** below was produced by running the installed package, not by reading
alone. The one item that depends on an external trigger (concurrency) is marked **unconfirmed** and says
so.

## Verdict

Ship-quality. The core safety path (tabular `enforce`: type-family matching, the observe/warn/enforce
ladder, the fail-closed readiness verdict, the reconcile registration gate) is correct, well factored,
and unusually well documented at the "why" level. No finding below breaks that path. The findings are
edge behaviors on the payload path, one resolver foot-gun, an export fidelity gap, and operational notes
on the event log. All are follow-ups, not blockers.

## What's strong

- **Type-family matching** (`families.py`) is the right call: it accepts an int stored as `float64`
  (what pandas does to a nullable int from CSV) while still rejecting a stringified number or a real
  decimal where an int was declared. Non-mutating, so validation can never launder drift.
- **Fail-closed everywhere it counts.** An empty or absent event log reads as "not ready," never green
  (`events_report.Report.summary`). An unrecognized `result` value is treated as blocked, not clean.
- **`reconcile` proves registration, not just declaration** by force-importing the package and diffing
  declared vs registered boundaries, plus an AST scan for decorators buried inside functions that would
  never run at import. That closes the "declared but silently never enforced" hole.
- **Comment density explains the reasoning, not the mechanics.** The `_validate_tabular` drop-rule
  comment (value-check-against-wrong-dtype ordering) and the `disabled()` stderr-not-logging rationale
  are the kind of notes that let a maintainer answer "why is it done this way" a year from now.

## Findings

### Medium

**M1 — a non-dict payload return crashes instead of failing cleanly.** `reproduced`

A payload boundary in `enforce` that returns a non-dict (an LLM handing back a JSON array instead of an
object, say) raises `AttributeError`, not `ContractViolation`. `runtime._validate_payload` does
`observed = {"keys": list(payload.keys())}` on line 241 before any validation, so a list return dies
there:

```
D. non-dict payload -> AttributeError: 'list' object has no attribute 'keys'
```

It fails closed (the job stops), so it is not a safety hole, but the operator gets an internal traceback
instead of `expected object, observed list`. Wrong-top-level-type is exactly the drift a contract should
name clearly.

*Follow-up:* guard the top of `_validate_payload` — if `payload` is not a `dict`, emit a `retyped`
`FieldDiff` (`expected object, observed <type>`) and route it through the normal violation path.

**M2 — a dotted partial version pin silently fails to resolve.** `reproduced`

`Resolver.resolve` treats any ref containing a dot as an exact filename lookup, so `@1` is a
major-range pin but `@1.0` is a literal `1.0.yaml` lookup. With only `1.0.0.yaml` on disk:

```
A. resolve @1   -> acme.widgets@1.0.0
A. resolve @1.0 -> SchemaNotFound('acme.widgets@1.0')
```

An author who writes `@1.0` expecting "highest 1.0.x" gets `SchemaNotFound`, which reads as "my schema
is missing" rather than "that is not how pins work." `lint` would catch it in CI, but the error does not
explain the real cause.

*Follow-up:* pick one — document that only `@MAJOR` is a range pin (dotted refs are exact files), or
support minor-pin semantics. At minimum, make the `SchemaNotFound` message distinguish "no such version
file" from "did you mean the `@MAJOR` range pin?"

**M3 — raw-`json_schema` payloads skip the closed-output extra-key check.** `reproduced`

For a fields-based payload, `to_json_schema` sets `additionalProperties: false` on an output boundary, so
an extra key surfaces as a `warn`. For a payload authored with a raw `json_schema`, the compiler returns
it verbatim and the `open` argument is ignored:

```
C. passthrough output schema additionalProperties = <absent -> extras allowed>
```

So two payload schemas that behave identically on inputs diverge on outputs: the fields-based one warns
on an added key, the passthrough one stays silent. Defensible (the author opted into raw JSON Schema and
owns its semantics) but surprising and undocumented.

*Follow-up:* document the asymmetry in the authoring skill, or have the passthrough path honor `open` by
setting `additionalProperties` when the raw schema does not pin it itself.

### Low

**L1 — ODCS export collapses `datetime` to `date`.** `reproduced`

`_ODCS_LOGICAL` maps both `date` and `datetime` to ODCS `date`, so a timestamp field loses its time
component in the exported contract (the JSON Schema compiler keeps the distinction via `date-time`):

```
B. datetime field -> ODCS logicalType='date' (declared 'datetime')
```

Likely an ODCS vocabulary limitation, but a downstream consumer reading the ODCS doc cannot tell a
timestamp from a date.

*Follow-up:* confirm intended; if it is a limitation, note it where ODCS export is described so it is a
documented loss, not a silent one.

**L2 — the event log grows unbounded and is read whole-file into memory.** `reproduced` (by inspection)

`events.EventLog` appends one line per validation with no rotation, and both `records()` and
`events_report.read_records` do `read_text()` over the entire file. Fine at pilot scale; on a hot
boundary in a long-running Cloud Run service the file grows without bound and every `contract events`
read loads all of it.

*Follow-up:* decide whose job rotation is and say so in the consuming-repo docs, or add a size cap /
rotation hint. Ties into the open "central sink" question below.

### Nits

**N1 — concurrent multi-process writers can tear a JSONL line.** `unconfirmed` (needs a real race)

`emit` does one `write()` per record; a line longer than the platform's atomic-write size, written by two
processes sharing one log, could interleave. The reader already tolerates this (skips and counts
malformed lines), so it degrades safely. Flagged only so a nonzero `skipped` count is not read as proof
of corruption. Not reproduced here because it depends on OS atomicity and true concurrency.

**N2 — `required`-field detection parses the jsonschema message string.** `reproduced` (by inspection)

`_validate_payload` recovers the missing field via `err.message.split("'")[1]`. It works against the
stable draft-2020-12 wording, but message-parsing is the exact anti-pattern the project deliberately
avoids elsewhere (`UndeclaredBoundary` is classified by type, not message). Low risk, worth a note.

**N3 — `to_json_schema(open=...)` shadows the builtin `open`.** `reproduced` (by inspection)

Harmless (ruff does not flag it), but `is_open` costs nothing and reads cleaner.

## Open design questions (for the author)

These are not code defects; they are the "how is this meant to be operated" gaps surfaced during review.

1. **Failure delivery.** In `enforce`, a mismatch raises and stops the job, but nothing pushes a
   notification. Surfacing it is on whoever runs the automation. Intended, or is a Slack/email hook
   planned?
2. **Observe visibility.** `observe` logs a mismatch but never raises. How does anyone learn a mismatch
   happened without manually running `contract events`? Is something meant to watch the log?
3. **Central sink.** The event log is a local file per process. For automations on Cloud Run / CI, where
   does it live, who reads it, and is a central sink (BigQuery, a shared bucket) on the roadmap? Is that
   the unbuilt "§15 item 5" hook?
4. **Adoption.** The authoring skill lives in this repo, so every consuming repo copies it in. Should it
   be promoted to the Avenue Z marketplace so repos pick it up automatically?

## Follow-up checklist

- [ ] M1 — clean `ContractViolation` for a non-dict payload return
- [ ] M2 — clarify or fix dotted partial version pins; sharpen the `SchemaNotFound` message
- [ ] M3 — document (or close) the passthrough-payload extra-key asymmetry
- [ ] L1 — document the ODCS `datetime` to `date` collapse
- [ ] L2 — decide event-log rotation ownership; document it
- [ ] N1 / N2 / N3 — optional cleanups
- [ ] Answer the four open design questions above
