# src/contract_core/events_report.py
"""Read the validation event log and summarize per-boundary readiness (design
`2026-07-24-event-log-reader-design.md`). CLI-only; not part of the public API (R9)."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contract_core.contract import Contract

# Worst-first ordering for the human view and for picking a system's headline.
_VERDICT_RANK = {"blocked": 0, "review": 1, "clean": 2}

# The keys `summarize` reads. A "tolerant" reader must reject a parseable-but-wrong-shape line
# (a scalar, an array, a foreign/old record missing a key) too — otherwise `summarize` blows up
# with a KeyError/TypeError, and the reader is tolerant of exactly one failure mode it advertised.
_REQUIRED_KEYS = frozenset({"system", "boundary", "schema", "version", "result", "observed_shape"})
# The four fields that form the grouping key — they MUST be str, or the dict key is unhashable and
# summarize crashes on a record read_records let through (e.g. `{"system": ["a"], ...}`).
_GROUPING_KEYS = ("system", "boundary", "schema", "version")


def _is_valid_record(obj: Any) -> bool:
    return (isinstance(obj, dict)
            and _REQUIRED_KEYS <= obj.keys()
            and all(isinstance(obj.get(k), str) for k in _GROUPING_KEYS)
            and isinstance(obj.get("observed_shape"), dict))


def read_records(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """Return (records, n_skipped) from a JSONL event log, tolerantly.

    Split on `path.exists()`, NOT `is_file()`: a non-existent path is empty (`([], 0)`), but a path
    that exists is read — so a directory or permission-denied file lets `OSError` propagate to the
    caller rather than being silently treated as "missing" (design §5). A blank/whitespace-only line
    is skipped and NOT counted (benign); a line that fails `json.loads` OR parses to something that
    is not a well-formed event record (`_is_valid_record`) is skipped **and** counted, so a foreign
    or truncated record can never reach `summarize` and crash it.
    """
    p = Path(path)
    if not p.exists():
        return [], 0
    records: list[dict[str, Any]] = []
    skipped = 0
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not _is_valid_record(obj):
            skipped += 1
            continue
        records.append(obj)
    return records, skipped


@dataclass
class BoundarySummary:
    system: str
    boundary: str
    schema: str
    version: str
    events: int
    n_pass: int
    n_warn: int
    n_violation: int
    n_other: int  # records whose `result` is none of pass/warn/violation — fail closed
    last_shape: dict[str, Any]
    verdict: str  # "clean" | "review" | "blocked"


@dataclass
class Unobserved:
    boundary: str
    schema: str   # from the contract's declared ref (a major pin), not a resolved version
    version: str


@dataclass
class SystemReport:
    system: str
    boundaries: list[BoundarySummary]
    unobserved: list[Unobserved] = field(default_factory=list)


@dataclass
class Report:
    systems: list[SystemReport]
    skipped: int = 0

    @property
    def summary(self) -> dict[str, Any]:
        counts = {"clean": 0, "review": 0, "blocked": 0}
        unobserved = 0
        observed = 0
        for sr in self.systems:
            for b in sr.boundaries:
                counts[b.verdict] += 1
                observed += 1
            unobserved += len(sr.unobserved)
        return {
            **counts,
            "unobserved": unobserved,
            "skipped": self.skipped,
            # Fail closed: a violation would hard-fail under enforce; an unexercised boundary can't
            # be judged; and NO observed boundary at all is zero evidence, not a green light — an
            # empty/absent log must never read as ready (design §4; the agent gate keys on this).
            #
            # `skipped` is DELIBERATELY not folded in. `ready` means "no blocking finding in the
            # records successfully read." A truncated final line (skipped == 1) is common and
            # benign; making it flip an otherwise-clean boundary to not-ready would be noise that
            # trains people to ignore the gate. An agent that needs evidence *completeness*, not
            # just cleanliness, must read `skipped` alongside `ready` — the two are separate facts
            # by design (a deliberate call; see the design doc §4 and CHANGELOG).
            "ready": counts["blocked"] == 0 and unobserved == 0 and observed > 0,
        }


def _verdict(n_warn: int, n_violation: int, n_other: int) -> str:
    # Pinned to the runtime invariant (runtime.py:149-166): a `violation` is emitted for any hard
    # diff regardless of mode and would hard-fail under enforce; a `warn` never hard-fails. An
    # `n_other` (a result value this reader does not recognise) is treated as blocked — fail closed,
    # never let an unclassifiable record read as clean.
    if n_violation or n_other:
        return "blocked"
    if n_warn:
        return "review"
    return "clean"


def _split_ref(ref: str) -> tuple[str, str]:
    """`peec.prompts_export@1` -> ('peec.prompts_export', '1'). A refless schema keeps ''."""
    name, _, version = ref.partition("@")
    return name, version


def summarize(records: list[dict[str, Any]], *, contract: Contract | None = None,
              skipped: int = 0) -> Report:
    """Group events into a per-boundary readiness Report. Pure — no I/O (design §2, §3)."""
    # Group by (system, boundary, schema, version) — a per-ref key, so a mid-observe drift shows as
    # two honest rows rather than a silent merge (design §3).
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for r in records:
        key = (r["system"], r["boundary"], r["schema"], r["version"])
        groups.setdefault(key, []).append(r)

    by_system: dict[str, list[BoundarySummary]] = {}
    for (system, boundary, schema, version), recs in groups.items():
        n_pass = sum(1 for r in recs if r["result"] == "pass")
        n_warn = sum(1 for r in recs if r["result"] == "warn")
        n_violation = sum(1 for r in recs if r["result"] == "violation")
        n_other = len(recs) - n_pass - n_warn - n_violation  # unrecognised result values
        by_system.setdefault(system, []).append(BoundarySummary(
            system=system, boundary=boundary, schema=schema, version=version,
            events=len(recs), n_pass=n_pass, n_warn=n_warn, n_violation=n_violation,
            n_other=n_other,
            last_shape=recs[-1]["observed_shape"],  # last in file order (design §4)
            verdict=_verdict(n_warn, n_violation, n_other),
        ))

    # --contract declares "I am reasoning about ONE system." Scope the whole report to it —
    # displayed boundaries, counts, AND `ready` — so an unrelated system's violation in a shared
    # log can't bleed into this contract's gate (unobserved is already system-scoped; ready must
    # match). With no contract, report every system in the log (the multi-system overview).
    if contract is not None:
        systems = {contract.system}
    else:
        systems = set(by_system)

    reports: list[SystemReport] = []
    for system in sorted(systems):
        boundaries = sorted(
            by_system.get(system, []),
            key=lambda b: (_VERDICT_RANK[b.verdict], b.boundary, b.version),
        )
        unobserved: list[Unobserved] = []
        if contract is not None and system == contract.system:
            # Match by (contract.system, name): the log is multi-system, so a bare-name match would
            # false-negative when another system's same-named boundary fired (design §3).
            observed_names = {b.boundary for b in boundaries}
            declared = [*contract.raw, *contract.inputs, *contract.outputs]
            for spec in declared:
                if spec.name not in observed_names:
                    name, ver = _split_ref(spec.schema_ref)
                    unobserved.append(Unobserved(boundary=spec.name, schema=name, version=ver))
        reports.append(SystemReport(system=system, boundaries=boundaries, unobserved=unobserved))

    return Report(systems=reports, skipped=skipped)


def _display_ref(schema: str, version: str) -> str:
    """`(schema, version)` -> `schema@version`, or just `schema` when the ref carries no version —
    so a refless declared boundary never renders a dangling `foo@` (design §6 nit)."""
    return f"{schema}@{version}" if version else schema


def to_dict(report: Report) -> dict[str, Any]:
    """The `--json` shape (design §4). JSON key is `pass`, not the Python-safe `n_pass`."""
    return {
        "systems": [
            {
                "system": sr.system,
                "boundaries": [
                    {"boundary": b.boundary, "schema": b.schema, "version": b.version,
                     "events": b.events, "pass": b.n_pass, "warn": b.n_warn,
                     "violation": b.n_violation, "other": b.n_other,
                     "last_shape": b.last_shape, "verdict": b.verdict}
                    for b in sr.boundaries
                ],
                "unobserved": [
                    {"boundary": u.boundary, "schema": u.schema, "version": u.version}
                    for u in sr.unobserved
                ],
            }
            for sr in report.systems
        ],
        "summary": report.summary,
    }


def _shape_str(shape: dict[str, Any]) -> str:
    if "columns" in shape:
        return f"cols=[{', '.join(map(str, shape['columns']))}]"
    if "keys" in shape:
        return f"keys=[{', '.join(map(str, shape['keys']))}]"
    return str(shape)


def render_human(report: Report) -> str:
    """The default human view (design §4 mockup): worst-first rows per system, boundary before ref,
    no counts on clean rows, one global summary line."""
    lines: list[str] = []
    for sr in report.systems:
        lines.append(f"{sr.system} — {len(sr.boundaries)} boundaries")
        for b in sr.boundaries:
            ref = _display_ref(b.schema, b.version)  # FULL resolved version — never @major (§4)
            row = f"  [{b.verdict}]  {b.boundary}  {ref}  {b.events} events"
            if b.verdict != "clean":
                extra = f", {b.n_other} unrecognized" if b.n_other else ""
                row += f"  ({b.n_pass} pass, {b.n_warn} warn, {b.n_violation} violation{extra})"
            lines.append(row)
            if b.verdict == "blocked" and b.n_violation:
                lines.append(f"      last shape: {_shape_str(b.last_shape)} — "
                             f"{b.n_violation} violation(s) would hard-fail under enforce")
            elif b.verdict == "blocked":  # blocked purely by an unclassifiable result
                lines.append(f"      {b.n_other} unrecognized result value(s) — "
                             f"cannot classify, treated as not-ready")
        for u in sr.unobserved:
            lines.append(f"  [unobserved]  {u.boundary}  {_display_ref(u.schema, u.version)}  "
                         f"(declared, never observed)")
    s = report.summary
    if report.skipped:
        lines.append(f"({report.skipped} malformed line(s) skipped)")
    verdict = "Ready to enforce" if s["ready"] else "Not ready"
    lines.append(f"{verdict}: {s['blocked']} blocked, {s['unobserved']} unobserved. "
                 f"{s['clean']} clean, {s['review']} needs review.")
    return "\n".join(lines)
