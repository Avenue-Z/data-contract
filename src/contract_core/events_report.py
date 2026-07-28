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


def read_records(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """Return (records, n_skipped) from a JSONL event log, tolerantly.

    Split on `path.exists()`, NOT `is_file()`: a non-existent path is empty (`([], 0)`), but a path
    that exists is read — so a directory or permission-denied file lets `OSError` propagate to the
    caller rather than being silently treated as "missing" (design §5). A blank/whitespace-only line
    is skipped and NOT counted (benign); only a non-blank un-parseable line (the truncated final
    line a crashed-mid-write log carries) increments `n_skipped`.
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
            records.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
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
        for sr in self.systems:
            for b in sr.boundaries:
                counts[b.verdict] += 1
            unobserved += len(sr.unobserved)
        return {
            **counts,
            "unobserved": unobserved,
            "skipped": self.skipped,
            # A violation would hard-fail under enforce; an unexercised boundary can't be judged.
            "ready": counts["blocked"] == 0 and unobserved == 0,
        }


def _verdict(n_warn: int, n_violation: int) -> str:
    # Pinned to the runtime invariant (runtime.py:149-166): a `violation` is emitted for any hard
    # diff regardless of mode and would hard-fail under enforce; a `warn` never hard-fails.
    if n_violation:
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
        by_system.setdefault(system, []).append(BoundarySummary(
            system=system, boundary=boundary, schema=schema, version=version,
            events=len(recs), n_pass=n_pass, n_warn=n_warn, n_violation=n_violation,
            last_shape=recs[-1]["observed_shape"],  # last in file order (design §4)
            verdict=_verdict(n_warn, n_violation),
        ))

    systems = set(by_system)
    if contract is not None:
        systems.add(contract.system)

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
                    name, ver = _split_ref(spec.schema)
                    unobserved.append(Unobserved(boundary=spec.name, schema=name, version=ver))
        reports.append(SystemReport(system=system, boundaries=boundaries, unobserved=unobserved))

    return Report(systems=reports, skipped=skipped)


def to_dict(report: Report) -> dict[str, Any]:
    """The `--json` shape (design §4). JSON key is `pass`, not the Python-safe `n_pass`."""
    return {
        "systems": [
            {
                "system": sr.system,
                "boundaries": [
                    {"boundary": b.boundary, "schema": b.schema, "version": b.version,
                     "events": b.events, "pass": b.n_pass, "warn": b.n_warn,
                     "violation": b.n_violation, "last_shape": b.last_shape, "verdict": b.verdict}
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
    """The default human view: worst-first rows per system, one global summary line."""
    lines: list[str] = []
    for sr in report.systems:
        lines.append(f"{sr.system} — {len(sr.boundaries)} boundaries")
        for b in sr.boundaries:
            ref = f"{b.schema}@{b.version}"  # FULL resolved version — never collapse to @major (§4)
            counts = f"({b.n_pass} pass, {b.n_warn} warn, {b.n_violation} violation)"
            lines.append(f"  [{b.verdict}] {ref}  {b.boundary}  {b.events} events  {counts}")
            if b.verdict == "blocked":
                lines.append(f"      last shape: {_shape_str(b.last_shape)} — "
                             f"{b.n_violation} violation(s) would hard-fail under enforce")
        for u in sr.unobserved:
            lines.append(f"  [unobserved] {u.schema}@{u.version}  {u.boundary}  "
                         f"(declared, never observed)")
    s = report.summary
    if report.skipped:
        lines.append(f"({report.skipped} malformed line(s) skipped)")
    verdict = "Ready to enforce" if s["ready"] else "Not ready"
    lines.append(f"{verdict}: {s['blocked']} blocked, {s['unobserved']} unobserved, "
                 f"{s['review']} review, {s['clean']} clean.")
    return "\n".join(lines)
