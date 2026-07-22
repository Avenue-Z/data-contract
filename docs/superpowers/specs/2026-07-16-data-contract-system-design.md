# Data Contract System — Design

**Date:** 2026-07-16
**Status:** Approved for planning
**Owner:** Paul Ramirez / Engineering

## 1. Purpose and motivating incidents

Avenue Z runs ~40 automations (reporting jobs, ad-spend pacing, TikTok/Asana/Supermetrics
integrations, dashboards). Two incidents motivate this system:

- **Incident #1 — vendor drift.** An upstream API changed its response shape under a running
  automation and broke it. The design doc and the code agreed perfectly; *reality* moved. Nothing
  in the codebase validated actual data against an expected shape at the boundary.
- **Incident #2 — spec rot.** An API failed to meet requirements during build, so the automation
  was switched from that API to a CSV export from the platform. This was a correct engineering
  decision, but the data shape diverged from the original design doc and nobody noticed. The pilot
  for this incident is `aivx-reports` (its git history contains the exact input-shape change).

These are **different failures caught by different checks**:

| Failure | Detection |
| --- | --- |
| Vendor changed the data under us (#1) | Runtime validation of real data against the contract |
| Code diverged from the design doc (#2) | Static reconciliation of declared boundaries vs. contract |

Both checks read the **same contract artifact**. Write the contract once; get both checks.

### Non-goals for v1 (deliberately deferred)

- **Undeclared-I/O scanner** (AST / audit-hook discovery of boundaries nobody declared). Novel and
  unsound-by-nature in Python; peer review + the authoring skill carry this load instead.
- **Scheduled canary** against live sources.
- **Human-facing catalog.** Contracts are an engineering artifact; consuming *agents* read the YAML.
- **JS as a data producer.** JS is validate-only in v1 (see §6).
- **Python as the single data-pull/manipulation layer.** A real architectural decision this project
  will produce evidence for, but not part of it.

## 2. Guiding design decisions

1. **Named, versioned, reusable schemas are the cornerstone.** I/O is declared as references to
   named schema artifacts, never as inline shapes. This is what makes the future system-to-system
   compatibility check (`A.outputs` satisfies `B.inputs`) a lookup rather than a shape comparison.

   **The Portable Core principle (named once; R5/R6/§9 all point here).** The artifact shared across
   languages, tools, and `compat` is the compiled JSON Schema, which carries only the *structural
   core*: field presence, type, nullability, and enums. Value-level and cross-field constraints
   (ranges, regex, cross-column checks, custom validators) are **not portable** — they can't be pushed
   into a cross-provider/cross-language schema (the Pandera-vs-JSON-Schema split, §3; the same
   limitation the research found for cross-provider LLM outputs). Everything downstream leans on this:
   `compat` reasons only over the core (so it stays language-neutral), JS validates only the core
   (R6), and richer checks are always a Python-side *local enrichment*, never part of the shared
   contract. When three places seem to re-derive "the portable schema is just the structural core,"
   this is the one statement they mean.
2. **Postel's law: inputs open, outputs complete.** *Input* contracts are **open** — they declare
   only the fields a system *depends on*; unknown extra fields pass. A vendor *adding* a column is a
   non-event; *removing* or *retyping* a required field is a hard failure. You don't control upstream,
   so inputs must tolerate additions. *Output* contracts are **authored complete** — a system declares
   everything it emits, because its output is the product it offers others and it *does* control it.
   **What `compat` soundness actually rests on — and why warn-only outputs are safe.** *(Load-bearing
   statement, currently cited from §5.2. If a fourth site comes to depend on it during the build, give
   it a named handle like the Portable Core principle above, rather than restating it.)* Precisely:
   `compat` *soundness* (never a false "compatible") rests on **declared output fields being present
   at runtime**, which is hard-enforced — a missing declared output field hard-fails. Output
   *completeness* (declaring everything you emit) is a separate property that buys `compat`
   **precision**, not soundness. So if an output contract drifts toward incompleteness — a field gets
   emitted but not declared — the only consequence is that `compat` may return a false *"incompatible"*
   (it thinks A doesn't provide a field A actually emits): conservative, in the safe direction, never
   a false "compatible." This is *why* the weakest enforcement in the system (the output `warn`) can
   be allowed to guard completeness: its failure mode is over-caution, not unsafety. Runtime
   enforcement of the asymmetry (§5.2, table): a *missing* declared field hard-fails at both input and
   output; an *extra* undeclared field passes silently on input and is a `warn` on output (surfaced so
   the contract gets updated, but never blocks a deliverable over an added field). Open inputs are also
   what make the compat check sound via structural subtyping.
3. **Hard-fail by default at runtime — but only because contracts are open.** A confidently-wrong
   client deliverable is worse than a missing one. Fail fast, fail loud, fail before doing work.
4. **Mediated sources get *two* boundaries: raw-call-site and normalized.** MCP and LLM response
   shapes are a function of the request, not a fixed vendor property. But contracting *only* the
   adapter's output moves the incident-#1 blast radius: an adapter that silently coerces a changed
   vendor shape into the old named schema makes validation pass on a lie, and vendor drift goes
   undetected. So for any mediated source (API/MCP), the **raw payload is contracted at the vendor
   edge, before the adapter** — this is the boundary that catches drift, and it is per-call-site (not
   shared). The adapter then normalizes to a shared, reusable named schema, which is contracted at its
   *output* for downstream consumers. Two boundaries, two purposes: raw = "did the vendor change?",
   normalized = "does downstream get what it expects?". File-ingest sources have only the single
   (normalized) boundary. See §7.
5. **Build on ODCS, but keep a reuse layer above it.** ODCS v3.1.0 is the surviving industry
   standard (the Data Contract Specification was deprecated in its favor). But ODCS cannot define a
   reusable type once and reference it across contracts. We keep reuse in a source layer we own and
   compile down to spec-valid ODCS.
6. **Reconciliation is a *sound diff over an import-time registration set*.** Decorators self-register
   boundaries; the check is `set(registered) ^ set(declared)`. The set operation is sound with no
   heuristics — but its input is only as complete as import-time execution (see §5.4 for the
   registration-completeness limitation and its mitigation). This is not a code analyzer and makes no
   attempt to be one.

## 3. Standards and libraries (research-backed)

- **ODCS v3.1.0** (Bitol / Linux Foundation, Apache 2.0) — the compiled interchange format. Pin the
  dated JSON Schema (`odcs-json-schema-v3.1.0-20260505.json`), not `-latest`.
- **`datacontract-cli` ~=1.0.12** (Apache 2.0) — production-grade real-data `test` (BigQuery,
  Postgres, S3, files-via-DuckDB, etc.) and 28-way format export. ODCS is its native model. Pin to a
  tested minor; treat major bumps as breaking.
- **Pandera ~=0.32.1** — Python tabular validation. Modern import is `import pandera.pandas as pa`.
  Supports pandas/polars/pyspark backends.
- **Pydantic ~=2.13** / JSON Schema 2020-12 — non-tabular ("payload") validation, Python side.
- **Ajv ^8** — JS validation (both tabular-as-array and payload), over the compiled JSON Schema.
  Configure it explicitly for the draft the compiled schema declares (see the draft-normalizer risk,
  §14).
- **Karapace** (Aiven, Apache 2.0) — vendor `compatibility/jsonschema/` (~4 files) at a pinned commit
  for the BACKWARD/FORWARD/FULL compatibility engine. Avoid Confluent's Java (JSON Schema compat is
  source-available, not OSI). Karapace is Draft-07; Pydantic emits 2020-12 → a normalization shim is
  required, and it is a **named, owned risk** (§14), not a footnote.

Exact versions are floors for the design; the authoritative pins live in the lockfile (§4.2 pinning
strategy applies to our own dependencies too).

**Confirmed gaps we must build ourselves:** ODCS→Pandera bridge (no prior art either direction);
breaking-change *classification* (Karapace gives structural compat; the semver rule table is ours);
Pandera schema-vs-schema compatibility (~50 lines; `DataFrameSchema.columns` is a plain dict);
the registry-diff reconciliation.

**Novelty note:** no OSS or commercial tool discovers Python I/O boundaries and diffs them against a
declared contract. The entire modern data stack (dbt `ref()`, Airflow inlets/outlets, Dagster
`@asset(deps=...)`) lets you declare I/O and none verify it against code. We are not duplicating —
but we deliberately scope to the *sound registry diff*, not the unsound static scanner.

## 4. Artifacts

Four artifact types. Three are authored; one is emitted at runtime.

### 4.1 Schema — a named, versioned, standalone shape

Lives at `schemas/<platform>/<name>/<semver>.yaml`. Namespaced by **source platform** (the stable
entity), not by owning team or automation. Immutable once published; a change is a new version.

```yaml
# schemas/tiktok_shop/orders_export/1.2.0.yaml
schema: tiktok_shop.orders_export
version: 1.2.0
kind: tabular            # tabular -> Pandera ; payload -> JSON Schema / Pydantic
fields:
  - name: order_id
    type: string
    required: true
  - name: gmv
    type: float
    required: true
    nullable: false
```

A schema knows nothing about who consumes it.

### 4.2 Contract — what one system consumes and emits

Lives in the automation's own repo (`contract.yaml`). Holds **references, never inline shapes**.
`inputs` and `outputs` are the sets that make future compatibility checking tractable.

```yaml
system: aivx-reports
version: 1.3.0
inputs:
  - name: peec_metrics
    schema: peec.brand_metrics@1        # major-pin; exact version in lockfile
    source: {kind: file, format: csv}
    mode: enforce                        # observe | warn | enforce | retry
outputs:
  - name: report_payload
    schema: aivx.report@1.0.0
    sink: {kind: file, format: json}
    mode: enforce
```

**Pinning strategy:** contracts pin by **major** (`@1`); a lockfile records the exact resolved
version; the event log records the exact version used at runtime. Low churn + reproducibility +
forensics.

### 4.3 Compiled ODCS document — generated, never edited

The compiler resolves every reference and inlines it, emitting a spec-valid ODCS v3.1.0 document
(for `datacontract-cli test` and interop) and a JSON Schema (the universal validation form for both
language runtimes). Exists solely because ODCS lacks cross-contract type reuse. If ODCS ever adds a
`definitions` block, this compiler collapses toward a no-op.

### 4.4 Validation event log — emitted at runtime

One structured record per boundary crossing: `{system, boundary, schema, version, result,
observed_shape, timestamp}`. Enables **fault localization** (the first failed boundary in a chain is
the fault site — bisect, don't debug the whole pipeline) and seeds the future canary. Designed in now
because provenance is miserable to retrofit.

## 5. Components

Five components: three libraries, a CLI, and a skill.

### 5.1 `contract-core` (Python) — resolver + compiler

The only component that understands the file formats. Resolves `platform.name@version` (local
repo `schemas/` first, then the central `avenue-z-schemas` package), loads and validates contract
files, and compiles source YAML → ODCS v3.1.0 + JSON Schema. The single place that papers over the
ODCS reuse gap.

### 5.2 Python runtime SDK — the boundary decorator

```python
@contract.input("peec.brand_metrics@1", mode="enforce")
def load_metrics(path) -> pd.DataFrame: ...
```

Triple duty: (i) **self-registers** the boundary (enables the reconciliation diff with zero code
analysis); (ii) **validates** on every call — Pandera for tabular, Pydantic/`jsonschema` for
payloads — honoring the modes; (iii) **emits a validation event**. Outputs validate *before* the
payload is published to its sink.

**Strictness (per decision #2) — the whole rule in one table.** Read this once instead of assembling
it from prose:

| | **Declared field missing / retyped** | **Extra undeclared field present** |
| --- | --- | --- |
| **Input** | hard-fail (`enforce`) | pass silently (open — decision #2) |
| **Output** | hard-fail (`enforce`) — incomplete deliverable is a defect | **`warn`** — surface it, never block for an added field |

Every cell is `enforce` except the two "extra field" cases; inputs ignore extras, outputs warn on
them. The mode ladder (`observe`/`warn`/`enforce`) can override a cell per boundary, but this is the
default the implementer codes to.

**What keeps outputs *complete*, given the extra-field case is only a `warn` (decided on purpose).**
A non-blocking log line is the easiest thing in this system to ignore, so it is worth stating plainly
that output completeness is guarded by the *weakest* enforcement here — deliberately. This is
acceptable only because of the soundness/precision split in decision #2: an undeclared-but-emitted
output field degrades `compat` *precision* (a false "incompatible"), never its *soundness*, so the
failure direction is safe. Completeness is maintained by three soft forces, not a gate: the `warn`
itself, the authoring skill at the point a field is added (§5.5), and code review. **Known residual:
nothing hard-catches "emitted an output field without declaring it" today** — Phase 2's semver-bump CI
check backstops *declared* output changes but not this omission. Accepted, not overlooked.

**Modes (v1):** `observe` (validate, never fail, log observed shape — the onboarding on-ramp) →
`warn` (log violation, continue) → `enforce` (hard-fail; the default).

**`retry` is cut from v1.** "Validate, retry N times, then fail" left the load-bearing questions
unspecified — retry *what* (re-invoke with the same prompt, or one augmented with the validation
diff?), cost/latency ceilings, and idempotency of side effects between attempts — and it is the one
mode that spends money and hammers a vendor per attempt. It is also partly redundant: JSON-repair for
malformed LLM output already lives in `glean-chat-api-client`. In v1, LLM-output boundaries use
`enforce` on top of whatever the client returns. `retry` is deferred until its backpressure semantics
are designed properly (§14).

### 5.3 JS runtime SDK (`@avenuez/data-contract`) — validate-only

Resolve a schema by name, compile with Ajv over the compiled JSON Schema, validate at the fetch
boundary, same three modes, same event format. **Does not** author contracts, declare output sets, or
participate in reconciliation. A JS system that calls an API directly gets incident-#1 protection but
does not appear in the daisy-chain graph as a producer (upgradeable later, additively).

### 5.4 `contract` CLI

- `lint` — references resolve? contract well-formed? (design-time + CI)
- `compile` — emit ODCS + JSON Schema
- `reconcile` — collect self-registered boundaries, diff against the contract. **Hard findings only**
  (decorator with no contract entry; contract entry no decorator implements). Blocking in CI.

  **Registration-completeness limitation (must be stated wherever `reconcile` is called sound).** The
  set *diff* is sound, but the registered set is only as complete as import-time execution: a boundary
  decorator registers only if its module is imported and the decorated function is *defined at import
  time*. Conditional imports, plugin/factory-created handlers, and decorators inside function bodies
  will not register, so `reconcile` can pass while a real drifted boundary was never seen — a false
  negative in a blocking gate. Mitigation: (a) `reconcile` **force-imports every boundary module** in
  the package (walk the package tree, import all), not just whatever the entrypoint pulls in; (b) a
  **lint rule bans boundary decorators outside module top-level scope**, so the "defined at import
  time" precondition is enforced rather than assumed. Residual gap: genuinely dynamic,
  factory-created boundaries remain undetectable by this mechanism and are an accepted limitation —
  the authoring skill steers away from that pattern.
- `compat A B` — does A's output set satisfy B's input set? Vendored Karapace. The future capability.

### 5.5 The authoring skill

Extends the existing superpowers design flow so a spec emits a `contract.yaml` alongside the markdown
and the implementation plan includes the boundary decorators. Makes contracts org-wide by default
rather than by individual discipline.

## 6. Language scope

- **Python:** full — contract authoring, decorator, runtime validation, hard-fail, event log,
  reconciliation.
- **JavaScript:** validate-only (§5.3). JS and Python **share the same named schemas** — validated
  against the same compiled JSON Schema. This keeps the door open for JS-as-producer or
  Python-consolidation without betting on either.

**The shared guarantee is the JSON-Schema-expressible core, not the full Pandera schema (R6).** For
tabular schemas, the Python runtime uses Pandera, which can express checks with no clean JSON Schema
analogue (value ranges, cross-column checks, custom validators, dtype-coercion and nullable
semantics). The *compiled JSON Schema* — the artifact both languages and `compat` consume — carries
only the structural core: presence, type, nullability, enums. So "a named schema means the same thing
in both languages" is true **only up to that core**: JS validates a strictly *weaker* form than
Python, and any Pandera-only check is a Python-side local enrichment JS does not see. This is
tolerable precisely because `compat` *also* reasons only over the structural core (the same reason
value constraints can't live in a portable schema, §3) — so the gap never corrupts compatibility
reasoning; it only means JS accepts some payloads Python's richer checks would reject. Authors who
need a check enforced in *both* languages must express it in the structural core, not as a
Pandera-only check. See R6.

The pilot (`aivx-reports`) is itself polyglot (Next.js/TS app + Python `agent/`), so it exercises
both runtimes.

## 7. Data flow (runtime)

**Mediated source (API / MCP) — two boundaries.** The raw-call-site contract at the vendor edge is
what actually catches vendor drift (incident #1); the normalized contract protects downstream:

```
vendor → @contract.raw(peec.raw_response@1)  → validate → event log   ← catches vendor drift
              ↓ fail: hard-stop, before adapter runs
         adapter (vendor-shaped, brittle; a dumb mapper, separately tested)
              ↓
         @contract.input(peec.brand_metrics@1) → validate → event log  ← protects downstream
              ↓ fail: hard-stop, before any work
         ... transform ...
         @contract.output → validate → publish to sink → event log
```

**File-ingest source — single boundary.** No adapter mediates a CSV, so there is one normalized
boundary:

```
file → @contract.input(peec.brand_metrics@1) → validate → event log
            ↓ fail: hard-stop
       ... transform ...  →  @contract.output → validate → publish → event log
```

The raw contract is **per-call-site and not promoted** (its shape is a function of the specific
request, so it is not reusable across systems). Only the normalized schema is a promotion candidate.
The adapter must be a pass-through mapper with its own test that fails on an unknown raw shape —
absorbing drift in the adapter is the one thing that would defeat criterion #1.

## 8. Error handling

A violation raises `ContractViolation` carrying the boundary, schema, version, and a **structural
diff** of expected-vs-observed — not a Pandera stack trace. Example message:

> `peec.brand_metrics@1.2.0` at input `peec_metrics`: required column `gmv` expected `float`,
> observed `object`.

The quality of this message is most of the product's felt value; a bad message trains people to
disable the check.

## 9. Versioning

Schemas version **independently of contracts** (a shared schema cannot be owned by one contract).
This enables staged migration (consumers adopt a new major on their own timeline), makes the
compatibility check expressible, and isolates change. Costs: two version numbers; version sprawl
(GC — deferred, see below); the diamond problem (two depended-on schemas encode conflicting
assumptions about a shared concept — **no automatic resolution; requires human adjudication;
deferred**, not "unsolvable"); and the risk that a mis-declared bump makes the compatibility engine
lie.

**Mitigation (mandatory, ships in Phase 2):** on any schema PR, CI runs the compatibility engine
between the old and new version, derives the change class (breaking / additive / patch), and **fails
if the declared semver bump doesn't match the actual change.** Same Karapace machinery as `compat`,
pointed at two versions of one schema. This is what makes independent versioning trustworthy.

**Version GC is deferred, and is not a four-word process.** A naive GC keyed on the event log alone
will delete a schema used only by a low-frequency job — and a quarterly job (~89 days idle) isn't
even the worst case: an annual or ad-hoc/manually-triggered automation has *no* cron cadence at all,
so "longer than the longest cron cadence" doesn't bound it. Therefore **static evidence is the
primary signal**: a version referenced by any contract's lockfile across all repos is live, period.
**Runtime evidence (the event log) is a supplement** — it can mark a statically-referenced version as
*hot* vs *cold*, but absence from the event log never by itself authorizes deletion. GC deletes only
versions that are (a) unreferenced by any lockfile *and* (b) cold in the event log for a grace window.
Deleting a live dependency is the failure mode; static-primary is what prevents it. Until GC is built,
old versions simply accumulate — a tolerable cost at current scale.

## 10. Topology and packaging

- **`data-contract` (this repo) — tooling.** `contract-core`, Python runtime SDK, CLI, skill, and
  the JS package.
- **`avenue-z-schemas` — the central registry.** *Data, not code* — just promoted schema YAML.
  Split from the tooling so promoting a schema (frequent, low-risk) never requires a tooling release
  (rare, high-risk).
- **Contracts** live in each automation's own repo, next to the code they describe.
- **Promotion path (hybrid):** schemas start local to a repo; the moment a second system needs one,
  it is promoted into `avenue-z-schemas`. Identical format → promotion is a file move + reference
  update, never a rewrite.

## 11. Testing

- Reconciliation and compatibility engines are pure functions (structure in, findings out) → unit
  tests, no I/O.
- Runtime SDK tested against fixture DataFrames/payloads including every failure path (the modes
  ladder is a silent-regression risk).
- Compiler output validated against the pinned ODCS JSON Schema.

## 12. Success criteria (literal tests)

The system works iff it replays both incidents:

1. **Incident #1 replay — type change.** Take the pilot's input fixture; change a field's type the way
   the vendor did. The automation must **hard-fail at the input boundary, before doing any work**,
   with an error naming the boundary, schema version, and exact field — not a `KeyError` downstream.
   For a mediated source this fires at the **raw** boundary (§7), which is the point of that boundary.
2. **Incident #1 replay — field removal.** Remove a required field from the input fixture. Must also
   hard-fail at the boundary. This is the *other* half of decision #2's **input rule** ("removing or
   retyping a required field is a hard failure") and exercises a different validator code path than a
   type change, so it is a distinct test, not a variant of #1.
3. **Incident #2 replay.** Swap an input from API to CSV in the code without touching the contract.
   `contract reconcile` must **fail in CI** and name the boundary that drifted. (Ground truth: the
   real change is in `aivx-reports` git history — pulling the exact commit is a Phase 0 task.)

Criteria 1–3 cover Phases 0–1. **Later phases must earn the same falsifiability when planned** — a
planning doc can say "tested deliverable," but at scoping time these become literal replays with named
fixtures, matching #1–#3:

- **#4 (Phase 2, `compat`)** — a fixture pair where A's output is genuinely compatible with B's input
  and `compat` must return SATISFIES, *and* a pair where a required field is absent/retyped and it
  must return NOT-SATISFIES with the offending field named. Both a true-positive and a true-negative,
  because a checker that always says one thing passes half of any single-direction test.
- **#5 (Phase 2/R1, draft normalizer)** — the round-trip corpus: a set of authored schemas where
  `normalize(2020-12)→Draft-07` must preserve every accept/reject decision; the test fails if any
  fixture's verdict flips across the normalization.

## 13. Phased rollout

- **Phase 0 — Prove the loop.** Format + resolver + compiler + Python runtime validation + `lint`.
  Pilot: `aivx-reports`. `observe` → inspect shape log → `enforce`. *Delivers incident-#1 protection
  on one system.* Gate: the onboarding loop must be pleasant before writing a second contract.
- **Phase 1 — Make it stick.** `reconcile` + CI wiring + the authoring skill. *Delivers incident-#2
  protection; new automations get contracts by default.*
- **Phase 2 — Compatibility engine.** Vendor Karapace; ship `compat`; add the schema semver-bump CI
  check. *Delivers the daisy-chain check and honest version numbers.*
- **Phase 3 — JS validate-only SDK.** *Delivers incident-#1 protection for dashboards' direct API
  calls.*

## 14. Known risks & owned items

Named so they don't evaporate. Each has an owner-phase; none is hand-waved.

**Close a row in the same PR that lands its mitigation.** This table is what anyone — human or agent —
answers "what is left?" from, and a row describing shipped work as pending is worse than a missing
row: it reads as authoritative and sends someone to rebuild what exists. That is not hypothetical.
R8 shipped 2026-07-20 and its row still said "Phase 1, decide before the type vocabulary hardens"
until 2026-07-21, and it produced exactly that wrong answer in the meantime. A closure needs the
date, the commit, and *which* of the offered options was taken — the row's own alternatives are the
first thing a reader will otherwise re-litigate.

| # | Risk | Where it bites | Owned by | Mitigation (in-spec) |
| --- | --- | --- | --- | --- |
| R1 | **JSON Schema draft normalizer.** Pydantic emits 2020-12; Karapace compat is Draft-07; Ajv must be configured per-draft. `$ref` siblings, `unevaluatedProperties`, and tuple validation (`prefixItems` vs `items`-array) changed between drafts. | The **compat boundary only** (Phase 2) — the Python runtime validator uses Pandera/Pydantic on 2020-12 directly and never round-trips through Draft-07. Failure = compat engine and runtime disagree about what a schema *means*. | Phase 2 (before `compat` ships) | Constrain the *authored* schema subset to the draft intersection (no `prefixItems`, no `unevaluatedProperties`), targeting **identity on the constrained subset** — not merely "near-identity" — enforced by a round-trip corpus test asserting normalize(2020-12)→Draft-07 preserves every accept/reject decision. The goal is no mismatch left to manage, not a managed mismatch. Scoped, tested deliverable. |
| R2 | **Adapter absorbs vendor drift.** An adapter that coerces a changed vendor shape into the old named schema makes post-adapter validation pass on a lie, defeating criterion #1. **This is the most important risk, and its mitigation must not rest on human discipline** (unlike R1/R3/R5, which are enforced by machinery). | Runtime, mediated sources | Phase 0 (baked into the boundary model) | Two boundaries per mediated source (§7): raw-call-site contract *before* the adapter catches drift; adapter is a tested pass-through that fails on unknown raw shape. **Enforced, not trusted: `reconcile` emits a finding when a raw boundary is declared but no adapter drift-test is found** (raw-boundary present ⇒ a test exercising an unknown-raw-shape rejection must exist), turning "we wrote the test" from a hope into a gate — the same machinery-over-discipline standard as R3's lint rule. Without this, R2 has R7's shape (silent, relies on people acting unprompted) but none of R7's measurability. |
| R3 | **`reconcile` registration completeness.** The diff is sound; its input set is only as complete as import-time execution. | CI blocking gate (false negative), Phase 1 | Phase 1 (before `reconcile` blocks) | Force-import all boundary modules; lint-ban boundary decorators outside module top-level; accept dynamic-factory boundaries as a residual gap (§5.4). |
| R4 | **`retry` mode semantics.** Cost/latency ceilings, same-vs-augmented reprompt, side-effect idempotency between attempts. | LLM-output boundaries | Deferred (post-v1) | Cut from v1 (§5.2); `enforce` + client-side JSON-repair covers LLM outputs meanwhile. |
| R5 | **Version GC deletes a live low-frequency dependency.** Annual/ad-hoc jobs have no cron cadence to bound a runtime-only grace window. | Maintenance tooling | Deferred | Static evidence (lockfile refs across all repos) is **primary** and alone keeps a version live; runtime event log is a supplement marking hot/cold; delete only when unreferenced *and* cold past a grace window (§9). |
| R6 | **JS validates a weaker form than Python.** Per the Portable Core principle (decision #1), the shared compiled JSON Schema carries only the structural core; Pandera value/cross-column/custom checks are Python-only, so JS accepts payloads Python would reject for the same named schema. | Cross-language validation of tabular schemas | Phase 3 (JS SDK) | `compat` also reasons only over the core, so compatibility is uncorrupted (§6, decision #1); checks that must hold in *both* languages are authored in the structural core, not as Pandera-only checks; document the weaker-form guarantee at the JS SDK boundary. |
| R7 | **Authoring skill underperforms silently.** The skill (§5.5) is what makes Phase 1's "new automations get contracts by default" true, but unlike the runtime it has no replay test — its failure is silent (people just don't write contracts) and uncaught. | Phase 1 adoption promise | Phase 1 | Dogfood on the next **N≥5** new automations; measure contract-adoption rate *without nagging* (adoption that needs a human reminder means the skill failed). **Threshold: <80% adopting a contract unprompted = skill defect**, revisit the skill — not a discipline problem. (Numbers are a starting placeholder so the risk can actually trip; tune once there's data.) |
| R8 | **Physical-dtype brittleness in tabular validation.** `to_pandera` compiles our logical `type` to one pandas dtype and validates with `coerce=False`, so a boundary hard-fails whenever pandas *infers* a different *physical* dtype for semantically-fine data: `int64` where the schema declared `float`/`Int64` (a client CSV with no null/decimal positions), `object` vs `str` across pandas 2↔3, or an all-null column arriving as `object`. Surfaced live in the Phase 0 pilot (pandas 3.0); it passed only because four verticals happened to infer identical dtypes. A drift-detector that false-positives on valid data is one people disable — worse than none. | Runtime tabular validation, **every consuming repo** | **Phase 1** (before `enforce` spreads past the pilot) | **CLOSED 2026-07-20** (`67e1b8d`, PR #7). Took the type-families option: `contract_core.families.dtype_satisfies` matches on logical families and `to_pandera` compiles `dtype=None` plus a non-mutating `dtype_family:<type>` check, so an inferred-but-equivalent dtype passes. `coerce=False` is retained and commented as load-bearing — it was never the fix, because coercion hides the drift criterion #1 exists to catch. The true-negatives are the load-bearing half and are tested: a stringified number fails, a real decimal declared `int` fails, `bool` and `int` stay distinct. An all-null column satisfies any type by design (its dtype is uninformative; `nullable` enforces null-tolerance separately). 21 tests in `tests/test_families.py`. |
| R9 | **Distribution & public API surface.** `contract-core` installs only as an editable local path at `0.0.1`, exports just `__version__`, and consumers import deep module paths (`contract_core.runtime`, `.contract`, `.errors`, `.resolver`). CI on another machine cannot install it, and any internal refactor breaks every consuming repo at once. Invisible from the pilot alone; a hard blocker for "first thing in every new repo." | Adoption / topology (§10) | **Phase 1** (prerequisite to repo #2) | Publish a versioned artifact (private index or pinned git-tag ref); curate a stable public API in `__init__.py` and treat deep module paths as private. **CLOSED 2026-07-21** — designed, implemented, merged, and released: `v0.1.0` is tagged on `main`, so `contract-core @ git+https://github.com/Avenue-Z/data-contract@v0.1.0` now resolves. Read [`CHANGELOG.md`](../../../CHANGELOG.md) for the release notes and [`docs/consuming-repo-setup.md`](../../consuming-repo-setup.md) for the consumer setup. The delivered surface is exactly five names — `load_runtime`, `ContractRuntime`, `ContractViolation`, `FieldDiff`, `__version__` — narrower than this row's original sketch: `Contract` and `Schema` were deliberately **excluded** as loading/authoring internals a consumer never needs, and `EventLog` excluded because exporting it would promise the sink hook §15 item 5 has not built. A frozen-surface test enforces the set. |
| R10 | **The authored format is itself unversioned.** The schema/contract YAML is the real API surface but carries no format-version; a `contract-core` format change breaks every repo's authored files with no migration — the system has a compatibility story for *data* (§9) but none for *its own artifacts*. | Format evolution across repos | **Phase 1/2** | Add an explicit format `apiVersion` to the schema and contract formats before broad adoption; define a format-compat policy (loudly reject/migrate an unknown format version, never silently mis-parse). |

## 15. Post-Phase-0 findings (2026-07-20)

Phase 0 shipped `contract-core` (plan Tasks 1–12) and the `aivx-reports` pilot (plan Tasks 13–16,
on a feature branch): both PEEC boundaries authored from the *real* export columns (not the plan's
placeholders), `observe`→`enforce`, criteria #1/#2 passing as literal tests, and the R2 drift-test
convention realized. Recorded here so the findings steer later phases instead of re-surfacing per repo.
The through-line: **most of the value is in `contract-core` as a reusable library, so most of the fixes
belong in this repo, not in any one pilot.**

**Validated by the pilot**
- The two-boundary model (§7, decision #4) works end-to-end on a real file-ingest + mapper pipeline;
  blame localizes (raw = did the vendor change, normalized = did our mapper drift).
- Criteria #1 (type change) and #2 (field removal) hard-fail at the boundary naming the field and the
  schema version (§12) — against a real adapter, not just fixtures.
- The R2 mitigation (§14) is concrete: a companion drift-test now exists, giving Phase 1's `reconcile`
  gate a real pattern to enforce rather than a described one.

**New — fix in `data-contract` (the library); every new repo inherits these**
1. **Physical-dtype brittleness → R8.** The single most important correctness finding. The pilot's
   green run was partly luck of inference. ***CLOSED 2026-07-20** (`67e1b8d`, PR #7) — logical type
   families replace exact-dtype equality. See the R8 row in §14 for what shipped and why
   `coerce=False` stayed.*
2. **Distribution + no stable public API → R9.** Editable-local-path install and deep imports are an
   adoption blocker, invisible from inside the pilot. ***CLOSED 2026-07-21.** Designed 2026-07-20,
   implemented and merged 2026-07-21, and **`v0.1.0` is tagged on `main`** — which is the step that
   actually delivered it, since until the tag existed a consumer pinning it got a resolve failure and
   the merged code alone delivered nothing. One release step remains outside this repo's automation:
   the §5 smoke test in `docs/consuming-repo-setup.md`, which is the only check covering the
   authenticated `git+https` fetch — no automated test can run it, because a tag cannot be installed
   before it is cut. §15 item 7 (the import-time-crash concern) is closed by the same work:
   `ContractRuntime.disabled()` and `load_runtime(enabled=...)` give the lazy/opt-out path it asked
   for.*
3. **The authored format is unversioned → R10.**
4. **No value-check enrichment hook yet.** Decision #1 (Portable Core) promises value/cross-field
   checks as a Python-side Pandera *enrichment*, but `to_pandera` emits only presence/type/nullability
   and the runtime applies exactly that — an author currently has **no way to attach** the enrichment
   the principle assumes. So the structural-core split is honored, but its other half is unbuilt. For
   this pilot that means the likely real corruption (sentiment out of range, `is_owned ∉ {0,1}`,
   negative ranks, empty `brand`) passes silently.
   ***CLOSED 2026-07-22** (`23f02d7`, PR #21), released as `v0.2.0`. Took the **declarative** option
   rather than an imperative attach-point: the enrichment is four optional keys on a field — `enum`,
   `minimum`, `maximum`, `min_length` — not a hook accepting arbitrary Pandera checks. That choice is
   the load-bearing one, because a declared constraint compiles to all three targets (Pandera, JSON
   Schema, ODCS) and stays portable, whereas a Python callable would be Python-only and would widen
   R6's weaker-form gap instead of leaving it where decision #1 put it. Deliberately NOT built:
   `pattern`, exclusive bounds, `maxLength`, `multipleOf`, and cross-field checks — cross-field is the
   one this item's title implies and it remains unbuilt, so "value/cross-field enrichment" is now
   **half** delivered, not whole. Applicability and satisfiability are validated at schema load (six
   rejections, enumerated in `CHANGELOG.md`); a violation reports the constraint, the offending row
   count and up to three samples. The exact corruption named above — sentiment out of range,
   `is_owned ∉ {0,1}`, negative ranks, empty `brand` — is the literal test suite in
   `tests/test_value_constraints.py`. Design: [`2026-07-21-value-constraints-design.md`](2026-07-21-value-constraints-design.md).*
5. **Library-hygiene defects to clear alongside the above:** `ContractRuntime.REGISTRY` is
   process-global mutable class state (leaks across contracts/tests — the pilot's registry assertion is
   already order-dependent); ~~an empty (0-row) result frame is reported as "all columns missing" instead
   of "structurally valid, no rows", so a gracefully-handled empty case becomes a confusing
   `ContractViolation`~~ — **this one no longer reproduces**: a 0-row frame carrying the declared
   columns now passes, because R8's family check treats an empty/all-null series as satisfying any
   type. Only a wholly column-less `pd.DataFrame()` fails, and reporting *that* as missing columns is
   correct. Closed as a side effect of `67e1b8d`, verified 2026-07-21; runtime error-classification
   parses library internals (`check ==
   "column_in_dataframe"`, `jsonschema` message-splitting) and is fragile across the pinned-dependency
   bumps; the `schema` field shadows `BaseModel.schema` (a `UserWarning` every run — use a Pydantic
   alias); the event log (§4.4) is a hardcoded local JSONL with no sink abstraction and, in `observe`,
   no reader — its whole value assumes someone reviews it.

**New — pilot/usage guidance (fix in the consuming repo + the §5.5 skill, not the library)**
6. **Decorate the true raw read, not a post-cleaning function.** The pilot decorated `load_prompts`,
   which strips/filters *before* returning, so it validates a partly-cleaned frame — weakening the
   "raw = vendor edge" guarantee of §7. The authoring skill should steer decoration to the pre-cleaning
   read (`pd.read_csv` output).
7. **Don't make import-time runtime construction the default.** The pilot builds the runtime at module
   import (file I/O + a hard `contract-core` dependency at import time), so anything importing the
   module hard-crashes without the library present. The library should offer a lazy / opt-in /
   `disabled()` path (ties to R9), and the skill should document it — the contract should degrade to a
   warning, not break an unrelated import.
8. **Direction modeling.** A produced-internally frame declared under `inputs:` inherits *open*
   (extra-field-silent) strictness (§5.2), so a forgotten schema update on a new output column is
   silent. If catching the producer's own drift is the goal, model it under `outputs:` (warn-on-extra).
   A clarification for the skill, not a code change.

**Gate answer (§13 — "was the onboarding loop pleasant?"):** Yes. Schemas authored from the real
columns matched on the first try across four verticals (digital-banks, payments, beauty, alts); no
reconciliation was needed. All friction lived in items 1–8, none of which blocked the pilot but all of
which **compound across repos**. Recommendation: clear **R8, R9, and item 4** before onboarding repo #2
— they are the difference between "drop it in and it helps" and "drop it in and it cries wolf / can't
install / silently misses the real bugs."

**Progress against that gate (2026-07-22): all three cleared.** R8 closed (`67e1b8d`) — it no longer
cries wolf. R9 closed and released as `v0.1.0` — it installs. Item 4 closed (`23f02d7`) and released
as `v0.2.0` — it no longer silently misses the real bugs: the corruption this pilot is most likely to
meet (sentiment out of range, `is_owned ∉ {0,1}`, negative ranks, empty `brand`) now hard-fails at the
boundary with a row count and samples.

**The onboarding-repo-#2 gate is therefore met.** What that does *not* mean is that Phase 1 is done —
clearing the gate was a precondition for adoption, not the phase. Still open before "new automations
get contracts by default" is true: `reconcile` and its R3 registration-completeness work, R2's
drift-test enforcement, the §5.5 authoring skill and R7's adoption measurement, and R10's format
`apiVersion`. Item 5's library-hygiene list is also still open, and one entry on it now matters more
than it did: **the event log still has no reader.** `v0.2.0`'s documented adoption path is "adopt the
constraint-bearing major in `observe`, read the event log, then promote to `enforce`" — that
instruction currently resolves to "parse the JSONL yourself."
