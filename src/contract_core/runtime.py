# src/contract_core/runtime.py
import functools
import logging
import os
from collections.abc import Callable
from typing import Any, Literal

import pandas as pd
import pandera.pandas as pa

from contract_core.compile.jsonschema_compile import to_json_schema
from contract_core.compile.pandera_compile import to_pandera
from contract_core.contract import BoundarySpec, Contract
from contract_core.errors import ContractViolation, FieldDiff
from contract_core.events import EventLog, Result
from contract_core.resolver import Resolver
from contract_core.schema import Schema

# A boundary decorator: wraps a data-producing function, validating its return value.
Decorator = Callable[[Callable[..., Any]], Callable[..., Any]]
Problem = Literal["missing", "retyped", "nullable", "extra"]

_LOG = logging.getLogger("contract_core")

# `CONTRACT_DISABLED` is an ops kill switch, so its activation rule is pinned, not "truthy"
# (R9 design §3.3): typing `0`/`false` must turn the switch OFF, not disable every contract.
_ENV_OFF_VALUES = frozenset({"", "0", "false", "no"})


def _env_disabled() -> bool:
    """Is the `CONTRACT_DISABLED` kill switch on? Present and not an off-value."""
    raw = os.environ.get("CONTRACT_DISABLED")
    if raw is None:
        return False
    return raw.strip().lower() not in _ENV_OFF_VALUES


def _default_clock() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


class ContractRuntime:
    REGISTRY: list[tuple[str, str]] = []

    def __init__(self, contract: Contract, resolver: Resolver,
                 event_log: EventLog | None = None,
                 clock: Callable[[], str] | None = None) -> None:
        self.contract = contract
        self.resolver = resolver
        self.event_log = event_log or EventLog()
        self.clock = clock or _default_clock

    @classmethod
    def disabled(cls, label: str | None = None) -> "ContractRuntime":
        """Return a no-op runtime and announce it once, loudly, on stderr.

        Turning validation off is itself a loud act (R9 design §3.3): "why is nothing
        validating?" must be diagnosable from a positive signal, not inferred from the
        absence of failures. Deliberately a log warning and NOT an event-log write — an
        event write is file I/O that can itself fail, reintroducing exactly the import-time
        crash graceful degradation exists to prevent.

        `label` is a best-available identifier (the factory passes the contract path). A
        disabled runtime reads no files, so it can never learn the contract's `system` name.
        """
        trigger = "CONTRACT_DISABLED set" if _env_disabled() else "explicitly disabled"
        _LOG.warning("contract validation DISABLED (%s) [%s]", trigger, label or "unspecified")
        return _DisabledRuntime()

    def _spec(self, direction: str, name: str) -> BoundarySpec:
        group = {"raw": self.contract.raw, "input": self.contract.inputs,
                 "output": self.contract.outputs}[direction]
        for b in group:
            if b.name == name:
                return b
        raise KeyError(f"no {direction} boundary named {name!r} in contract")

    def raw(self, name: str) -> Decorator:
        return self._decorator("raw", name)

    def input(self, name: str) -> Decorator:
        return self._decorator("input", name)

    def output(self, name: str) -> Decorator:
        return self._decorator("output", name)

    def _decorator(self, direction: str, name: str) -> Decorator:
        spec = self._spec(direction, name)
        resolved = self.resolver.resolve(spec.schema)
        ContractRuntime.REGISTRY.append((direction, name))

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                data = fn(*args, **kwargs)
                self._validate(direction, spec, resolved, data)
                return data
            return wrapper
        return deco

    # ---- validation ----

    def _validate(self, direction: str, spec: BoundarySpec, resolved: Schema,
                  data: Any) -> None:
        is_output = direction == "output"
        if resolved.kind == "tabular":
            diffs, observed = self._validate_tabular(resolved, data, is_output)
        else:
            diffs, observed = self._validate_payload(resolved, data, is_output)

        hard = [d for d in diffs if d.problem in ("missing", "retyped", "nullable")]
        extra = [d for d in diffs if d.problem == "extra"]

        result: Result
        if hard:
            result = "violation"
        elif extra and is_output:
            result = "warn"
        else:
            result = "pass"

        self.event_log.emit(
            system=self.contract.system, boundary=spec.name,
            schema=resolved.schema, version=resolved.version,
            result=result, observed_shape=observed, timestamp=self.clock(),
        )

        if hard and spec.mode == "enforce":
            raise ContractViolation(boundary=spec.name, schema_ref=resolved.ref,
                                    direction=direction, diffs=hard)

    def _validate_tabular(self, resolved: Schema, df: pd.DataFrame,
                          is_output: bool) -> tuple[list[FieldDiff], dict[str, Any]]:
        assert resolved.fields is not None  # tabular schema always has fields
        observed: dict[str, Any] = {"columns": list(df.columns),
                                    "dtypes": {c: str(t) for c, t in df.dtypes.items()}}
        diffs: list[FieldDiff] = []
        ps = to_pandera(resolved, strict=False)
        try:
            ps.validate(df, lazy=True)
        except pa.errors.SchemaErrors as err:
            for _, row in err.failure_cases.iterrows():
                check = str(row.get("check", ""))
                problem: Problem
                if check == "column_in_dataframe":
                    # missing required column: name is in `failure_case`, not `column`.
                    field = str(row.get("failure_case"))
                    problem = "missing"
                    field_observed = "absent"
                else:
                    # a dtype/value check on a present column: name is in `column`.
                    col = row.get("column")
                    if col is None or (isinstance(col, float) and pd.isna(col)):
                        continue
                    field = str(col)
                    if check == "not_nullable":
                        # a null-tolerance violation, not a type change: don't
                        # mislabel it `retyped` with a (valid) dtype as observed.
                        problem = "nullable"
                        field_observed = "null"
                    else:
                        problem = "retyped"
                        field_observed = str(df.dtypes.get(field, "absent"))
                declared = next((f for f in resolved.fields if f.name == field), None)
                expected = declared.type if declared else "?"
                diffs.append(FieldDiff(field=field, expected=str(expected),
                                       observed=field_observed, problem=problem))
        # de-dup by field
        seen: dict[str, FieldDiff] = {}
        for d in diffs:
            seen[d.field] = d
        diffs = list(seen.values())
        if is_output:
            declared_names = {f.name for f in resolved.fields}
            for c in df.columns:
                if c not in declared_names:
                    diffs.append(FieldDiff(field=str(c), expected="absent",
                                           observed=str(df.dtypes[c]), problem="extra"))
        return diffs, observed

    def _validate_payload(self, resolved: Schema, payload: dict[str, Any],
                          is_output: bool) -> tuple[list[FieldDiff], dict[str, Any]]:
        import jsonschema
        observed: dict[str, Any] = {"keys": list(payload.keys())}
        js = to_json_schema(resolved, open=not is_output)
        diffs: list[FieldDiff] = []
        validator = jsonschema.Draft202012Validator(js)
        for err in validator.iter_errors(payload):
            if err.validator == "required":
                # message: "'x' is a required property"
                missing = err.message.split("'")[1]
                diffs.append(FieldDiff(field=missing, expected="present",
                                       observed="absent", problem="missing"))
            elif err.validator == "type" and err.path:
                field = str(err.path[-1])
                diffs.append(FieldDiff(field=field, expected=str(err.validator_value),
                                       observed=type(err.instance).__name__, problem="retyped"))
            elif err.validator == "additionalProperties" and is_output:
                # closed output: name the extras
                declared = set((resolved.json_schema or {}).get("properties", {})) \
                    if resolved.json_schema else {f.name for f in (resolved.fields or [])}
                for k in payload:
                    if k not in declared:
                        diffs.append(FieldDiff(field=str(k), expected="absent",
                                               observed=type(payload[k]).__name__,
                                               problem="extra"))
        return diffs, observed


def _passthrough(fn: Callable[..., Any]) -> Callable[..., Any]:
    """The identity decorator: no wrapper, no validation, no events, no overhead."""
    return fn


class _DisabledRuntime(ContractRuntime):
    """Every boundary is a pass-through. Reachable only via `ContractRuntime.disabled()`.

    It deliberately does not call `ContractRuntime.__init__`: a disabled runtime has no
    contract and no resolver, and *acquiring* them is the file I/O this class exists to
    avoid. Touching `.contract` or `.resolver` on one is an error, by construction.
    """

    def __init__(self) -> None:
        pass

    def raw(self, name: str) -> Decorator:
        return _passthrough

    def input(self, name: str) -> Decorator:
        return _passthrough

    def output(self, name: str) -> Decorator:
        return _passthrough
