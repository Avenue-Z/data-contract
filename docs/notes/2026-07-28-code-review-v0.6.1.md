# contract-core v0.6.1 — code review

Full-library review of the merged code at `0.6.1` (dev == main, tree-identical). Reviewer: Thomas.
Documentation only: this file changes no code. Every finding lists a fix as a follow-up for the author;
nothing here edits the reviewed branch.

## Method

Read end to end, then run. Every finding tagged **reproduced** was produced against the installed
package (the repros are in this repo's review scratch, summarized inline). The findings survived a
second adversarial pass whose job was to refute them: that pass removed three low-value nits, refuted
one outright (multiple missing required fields are in fact all reported), and surfaced two issues the
first pass missed (F1 and F2 below) plus corrected the ODCS finding (F3). What remains is the set that
held up.

Green baseline, re-run:

- `pytest` — **295 passed**
- `mypy --strict` — **clean** (17 source files)
- `ruff check` — **clean**
- Version parity across `__init__`, `pyproject`, and the released tag — **0.6.1**.

## Verdict

Ship-quality. The tabular `enforce` core (type-family matching, fail-closed readiness, the reconcile
registration gate) is correct and unusually well documented at the "why" level. The findings cluster on
the **payload path**, the **wrong-type-return path**, and the **ODCS export path**, plus two DX
papercuts. None require holding the release; F1 and F2 are worth a fast-follow because both let bad or
breaking outcomes through silently.

## Completeness (why this is not a moving target)

Coverage was made measurable rather than asserted, so this review has a stopping criterion:

- **Behavior matrix, exhaustive.** Every combination of `{tabular, payload}` x `{input, output}` x
  `{observe, warn, enforce}` x `{valid, missing, retyped, nullable, value, extra}` was executed and its
  `(event result, raised?)` checked against the documented semantics: **39/39 correct.** Hard drift logs
  a violation in every mode and raises only under `enforce`; extra-on-output warns and never raises;
  extra-on-input passes. The core decision logic is proven, not sampled.
- **Branch coverage: 95%** (`pytest --cov --cov-branch`). Every uncovered line was read and classified.
  The behavioral ones (tabular extra-column warn, payload retyped/extra, the family "reject a
  stringified int" branch, ODCS export of a `json_schema` payload) are covered by the matrix above and
  by F1 to F6. The rest are defensive error branches (`except SyntaxError: continue`, unreadable-file
  rendering, a single-module package fallback, a legacy `EventLog.records()` the CLI does not call) with
  no behavior to get wrong.
- **Finding rate is decaying.** Pass 1 (read) produced a noisy list; pass 2 (adversarial) netted the two
  Mediums and cut the noise; pass 3 (coverage + matrix) proved the core and added one Low (F6). No new
  Medium-or-higher issue has appeared since pass 2.

Residual risk this method cannot close, stated honestly: behavior gated on a real external trigger (true
multi-process concurrency on one log; `reconcile` against a real consumer package) is reasoned about,
not executed here, and future code is out of scope. Short of those, the surface is covered.

## What's strong

- **Type-family matching** (`families.py`): accepts an int stored as `float64` while still rejecting a
  stringified number or a real decimal where an int was declared. Non-mutating, so it can never launder
  drift.
- **Fail-closed readiness**: an empty or absent event log reads as "not ready," never green; an
  unrecognized `result` is treated as blocked (`events_report`).
- **`reconcile` proves registration, not just declaration**: force-imports the package, diffs declared
  vs registered, and AST-scans for decorators buried inside functions that would never run at import.
- **Comments carry reasoning, not mechanics** (the `_validate_tabular` drop-rule ordering, the
  `disabled()` stderr-not-logging rationale). A maintainer can answer "why this way" a year out.

## Findings

### F1 — Medium — observe mode does not isolate the job from a wrong-type return `reproduced`

Observe mode is documented as "validate, **never fail**, log observed shape" (design §237, `SKILL.md`),
and it is the adoption on-ramp: the whole "switch it on in prod to build confidence" story depends on
observe being unable to break a working job. It can. `runtime._validate_tabular` / `_validate_payload`
call `.columns` / `.keys()` on the returned value before any validation, and there is **no type guard
anywhere in `runtime.py`**. A decorated function that returns the wrong top-level type raises a raw
`AttributeError` in **every** mode, observe included:

```
tabular output returns None  -> AttributeError: 'NoneType' object has no attribute 'columns'
payload output returns list  -> AttributeError: 'list' object has no attribute 'keys'
tabular input  returns dict  -> AttributeError: 'dict' object has no attribute 'columns'
```

A forgotten `return` (None) or a producer handing back a dict instead of a DataFrame now becomes a hard
crash the moment a contract is added in observe. That is the opposite of the on-ramp's promise, and it
is untested (no test pins this behavior).

*Follow-up:* type-guard the top of `_validate` — a wrong top-level type should be a clean `retyped`
`FieldDiff` (`expected object/dataframe, observed <type>`), which then hard-fails under `enforce` and
merely logs under `observe`/`warn`. More broadly, consider making `observe`/`warn` swallow-and-log any
unexpected validation exception, so "never fail the job" holds structurally rather than per-known-case.
(This subsumes the narrower "non-dict payload under enforce raises `AttributeError`" case.)

### F2 — Medium — payload `date`/`datetime` fields are not value-validated `reproduced`

The tabular path enforces a real datetime dtype. The payload path compiles `date` to
`{"type": "string", "format": "date"}`, but `_validate_payload` builds a `Draft202012Validator` with
**no `format_checker`**, and JSON Schema `format` is annotation-only by default. So temporal payload
fields are checked for string-ness and nothing else:

```
payload {"when": "not-a-date", "ts": "also-not-a-datetime", ...}  -> PASSED (enforce)
payload {"when": 12345, ...}                                      -> retyped (int caught: string-ness works)
```

A malformed date in a payload deliverable passes silently, which is exactly the class of defect the tool
exists to stop, and it is asymmetric with the tabular path.

*Follow-up:* enforce temporal formats — pass a `format_checker` to the validator (note `date-time`
needs an RFC 3339 validator dependency to actually check; `date` works off `date.fromisoformat`), or
validate temporal fields explicitly. If enforcement is intentionally deferred, stop emitting `format`
and document that payload temporal fields are string-only, so the schema does not imply a check it does
not run.

### F3 — Low — ODCS export maps `datetime` to `date`, losing the time component `reproduced`

`_ODCS_LOGICAL` maps both `date` and `datetime` to ODCS `date`. This is not an ODCS limitation: the
vendored v3.1 schema's `logicalType` enum is `["string", "date", "timestamp", "time", "number",
"integer", "object", "array", "boolean"]` — it has a distinct `timestamp`. So a timestamp field exports
as a plain date, and a consumer reading the ODCS contract cannot tell them apart.

```
datetime field -> ODCS logicalType='date'   (should be 'timestamp')
```

*Follow-up:* map `datetime` to `timestamp` in `_ODCS_LOGICAL`. One-line fix; `date` stays `date`.

### F4 — Low — a dotted partial version pin misresolves with a misleading error `reproduced`

`Resolver.resolve` treats any ref with a dot as an exact filename lookup, so only `@MAJOR` (range) and
`@X.Y.Z` (exact) are real forms. A semver-style minor pin `@1.0` becomes a literal `1.0.yaml` lookup and
fails even when `1.0.0.yaml` exists:

```
resolve @1    -> acme.widgets@1.0.0
resolve @1.0  -> SchemaNotFound('acme.widgets@1.0')
```

Only `@1` and `@1.0.0` are used or taught anywhere in the repo, so this is a papercut, not a broken
feature. But `@1.0` is a near-universal convention, and `SchemaNotFound` misdiagnoses it as "schema
missing."

*Follow-up:* sharpen the `SchemaNotFound` message to distinguish "no such version file" from "did you
mean the `@MAJOR` range pin?", or document the two supported pin forms explicitly. (Supporting minor
pins is a bigger call; the message fix is the cheap win.)

### F5 — Low — raw-`json_schema` payloads skip the closed-output extra-key warn `reproduced`

A fields-based payload gets `additionalProperties: false` on an output boundary, so an extra key
surfaces as a `warn`. A payload authored with a raw `json_schema` is returned verbatim and the `open`
argument is ignored, so `additionalProperties` is absent (extras allowed) and no warn fires:

```
passthrough output schema additionalProperties = <absent -> extras allowed>
```

Two payload schemas that behave identically on inputs diverge on outputs. Defensible (the author owns a
raw schema) but undocumented and surprising.

*Follow-up:* note the asymmetry in the authoring skill, or have the passthrough path set
`additionalProperties` from `open` when the raw schema does not pin it.

### F6 — Low — a `json_schema` payload exports to ODCS with an empty schema block `reproduced`

`odcs._schema_block` only walks `resolved.fields`. A payload authored with a raw `json_schema` has
`fields is None`, so it exports as a named table with **no properties** — the whole shape is silently
dropped from the ODCS document (and `lint`, which runs `to_odcs` + `validate_odcs`, still passes):

```
ODCS json_schema-payload props: []   (shape dropped from export)
```

Same root as F5: `json_schema` payloads are second-class on the export side too.

*Follow-up:* translate the raw `json_schema` `properties` into ODCS `properties`, or, if that is out of
scope, have `to_odcs` skip the boundary explicitly rather than emit a hollow block.

## Open questions (operability, not defects)

The event log being a local per-process JSONL with no sink is already a documented deferral (design
§528: "hardcoded local JSONL with no sink abstraction"; `EventLog` is kept off the public API precisely
because the sink hook is unbuilt). Not re-filed as a defect. The live questions for the author:

1. **Failure delivery.** In `enforce`, a mismatch raises and stops the job, but nothing pushes a
   notification. Surfacing it is on whoever runs the automation. Intended, or is a Slack/email hook
   planned?
2. **Observe visibility.** `observe` logs but never raises. How does anyone learn a mismatch happened
   without manually running `contract events`? Is something meant to watch the log?
3. **Central sink.** For automations on Cloud Run / CI, where does the local log live, who reads it, and
   is a central sink (BigQuery, a shared bucket) the planned "§15 item 5" hook?
4. **Adoption.** The authoring skill lives in this repo, so every consuming repo copies it in. Should it
   be promoted to the Avenue Z marketplace so repos pick it up automatically?

## Follow-up checklist

- [ ] F1 — type-guard wrong-type returns; make `observe`/`warn` never crash the job
- [ ] F2 — enforce payload temporal formats, or stop emitting `format` and document string-only
- [ ] F3 — map `datetime` to ODCS `timestamp`
- [ ] F4 — sharpen the `SchemaNotFound` message / document supported pin forms
- [ ] F5 — document (or close) the passthrough-payload extra-key asymmetry
- [ ] F6 — export `json_schema` payload shape to ODCS, or skip the boundary instead of emitting an empty block
- [ ] Answer the four open questions above

## What was considered and dropped

Kept out deliberately, so the list above stays high-signal:

- **Multiple missing required fields under-reported** — tested false. All missing fields are reported
  (`jsonschema` emits one `required` error each; `_validate_payload` handles each). No issue.
- **Concurrent writers tearing a JSONL line** — speculative, unreproduced, and the reader already
  degrades safely by skipping malformed lines. Not worth action.
- **`open=` kwarg shadowing the builtin in `to_json_schema`** — cosmetic; `ruff` does not flag it.
