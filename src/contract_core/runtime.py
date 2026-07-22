# src/contract_core/runtime.py
import functools
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa

from contract_core.compile.jsonschema_compile import to_json_schema
from contract_core.compile.pandera_compile import (
    DTYPE_CHECK_PREFIX,
    VALUE_CHECK_NAMES,
    to_pandera,
)
from contract_core.contract import BoundarySpec, Contract
from contract_core.errors import ContractViolation, FieldDiff
from contract_core.events import EventLog, Result
from contract_core.resolver import Resolver
from contract_core.schema import Schema
from contract_core.types import Field as FieldSpec

# A boundary decorator: wraps a data-producing function, validating its return value.
Decorator = Callable[[Callable[..., Any]], Callable[..., Any]]

# `CONTRACT_DISABLED` is an ops kill switch, so its activation rule is pinned, not "truthy"
# (R9 design §3.3): typing `0`/`false`/`off` must turn the switch OFF, not disable every contract.
_ENV_OFF_VALUES = frozenset({"", "0", "false", "no", "off"})


def _env_disabled() -> bool:
    """Is the `CONTRACT_DISABLED` kill switch on? Present and not an off-value."""
    raw = os.environ.get("CONTRACT_DISABLED")
    if raw is None:
        return False
    return raw.strip().lower() not in _ENV_OFF_VALUES


def _default_clock() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


def _failure_field(row: Any) -> str | None:
    """The field a pandera failure case belongs to.

    For `column_in_dataframe` the field name is in `failure_case` and `column` is NaN, so a
    group-by on the raw `column` would put every missing column in one NaN bucket
    (design §5.2.1).
    """
    if str(row.get("check", "")) == "column_in_dataframe":
        return str(row.get("failure_case"))
    col = row.get("column")
    if col is None or (isinstance(col, float) and pd.isna(col)):
        return None
    return str(col)


def _constraint_label(check: str, declared: "FieldSpec | None") -> str:
    """`maximum=1.0` — what the operator needs to see, from the schema not the frame."""
    if declared is None:
        return check
    value = {"enum": declared.enum, "minimum": declared.minimum,
             "maximum": declared.maximum, "min_length": declared.min_length}[check]
    return f"{check}={value}"


class ContractRuntime:
    REGISTRY: list[tuple[str, str]] = []

    def __init__(self, contract: Contract, resolver: Resolver,
                 event_log: EventLog | None = None,
                 clock: Callable[[], str] | None = None) -> None:
        self.contract = contract
        self.resolver = resolver
        self.event_log = event_log or EventLog()
        self.clock = clock or _default_clock

    @staticmethod
    def disabled(label: str | None = None) -> "ContractRuntime":
        """Return a no-op runtime and announce it once, loudly, on stderr.

        Turning validation off is itself a loud act (R9 design §3.3): "why is nothing
        validating?" must be diagnosable from a positive signal, not inferred from the
        absence of failures. Deliberately NOT an event-log write — an event write is file
        I/O that can itself fail, reintroducing exactly the import-time crash graceful
        degradation exists to prevent.

        Deliberately a bare stderr write and NOT `logging.warning`, either: the consumer
        doc's guarantee is that the absence of this line means validation is on, and a
        single `basicConfig`/`dictConfig` in the consuming app can delete a log record.
        A signal the consumer can silently reconfigure away is not a kill-switch
        announcement — it reintroduces the inference-from-silence foot-gun.

        `label` is a best-available identifier (the factory passes the contract path). A
        disabled runtime reads no files, so it can never learn the contract's `system` name.
        """
        trigger = "CONTRACT_DISABLED set" if _env_disabled() else "explicitly disabled"
        print(f"contract validation DISABLED ({trigger}) [{label or 'unspecified'}]",
              file=sys.stderr)
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

        hard = [d for d in diffs if d.problem in ("missing", "retyped", "nullable", "value")]
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
        ps = to_pandera(resolved, strict=False)
        cases: list[tuple[str, str, Any]] = []
        try:
            ps.validate(df, lazy=True)
        except pa.errors.SchemaErrors as err:
            for _, row in err.failure_cases.iterrows():
                field = _failure_field(row)
                if field is None:
                    continue
                cases.append((field, str(row.get("check", "")), row.get("failure_case")))

        # Drop rule FIRST, aggregation second (design §5.2.2). A value check against a
        # wrong dtype raises, and pandera records the TypeError as the failure case —
        # aggregating first would compute counts and samples off exception reprs.
        wrong_dtype = {f for f, c, _ in cases if c.startswith(DTYPE_CHECK_PREFIX)}
        cases = [(f, c, v) for f, c, v in cases
                 if not (f in wrong_dtype and c in VALUE_CHECK_NAMES)]

        groups: dict[tuple[str, str], list[Any]] = {}
        for field, check, value in cases:
            groups.setdefault((field, check), []).append(value)

        # Structural diffs collapse per field ("column missing" twice is noise); value
        # diffs do not collapse across constraints, because `minimum` and `maximum` on one
        # field are two distinct facts (design §5.2.1).
        structural: dict[str, FieldDiff] = {}
        diffs: list[FieldDiff] = []
        for (field, check), values in groups.items():
            declared = next((f for f in resolved.fields if f.name == field), None)
            expected = str(declared.type) if declared else "?"
            observed_dtype = str(df.dtypes.get(field, "absent"))
            if check in VALUE_CHECK_NAMES:
                diffs.append(FieldDiff(
                    field=field, expected=expected, observed=observed_dtype,
                    problem="value", constraint=_constraint_label(check, declared),
                    violating_rows=len(values),
                    samples=[str(v) for v in values[:3]],
                ))
            elif check == "column_in_dataframe":
                structural[field] = FieldDiff(field=field, expected=expected,
                                              observed="absent", problem="missing")
            elif check == "not_nullable":
                # a null-tolerance violation, not a type change: don't mislabel it
                # `retyped` with a (valid) dtype as observed.
                structural[field] = FieldDiff(field=field, expected=expected,
                                              observed="null", problem="nullable")
            else:
                structural[field] = FieldDiff(field=field, expected=expected,
                                              observed=observed_dtype, problem="retyped")
        diffs = [*structural.values(), *diffs]
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
            elif err.validator in ("enum", "minimum", "maximum", "minLength"):
                # Design §5.3: without this branch a jsonschema value error matches no
                # branch and is dropped, so constraints compile into the payload schema
                # and then do nothing.
                field = str(err.path[-1]) if err.path else "?"
                # NOT named `declared`: the additionalProperties branch below binds that
                # name to a set of field names, and one name for two types is a mypy error.
                declared_field = next(
                    (f for f in (resolved.fields or []) if f.name == field), None)
                key = {"minLength": "min_length"}.get(str(err.validator), str(err.validator))
                diffs.append(FieldDiff(
                    field=field, expected=str(declared_field.type) if declared_field else "?",
                    observed=type(err.instance).__name__, problem="value",
                    constraint=_constraint_label(key, declared_field),
                    violating_rows=None, samples=[str(err.instance)],
                ))
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


def load_runtime(
    contract_path: str | Path = "contract.yaml",
    *,
    schema_paths: Sequence[str | Path] = ("schemas",),
    enabled: bool = True,
) -> ContractRuntime:
    """Build a runtime from a contract file, or a disabled no-op runtime.

    Returns a disabled runtime — no validation, no file I/O, one loud warning at
    construction — when CONTRACT_DISABLED is *on* in the environment OR when
    enabled=False. CONTRACT_DISABLED is on iff present and not in
    {"", "0", "false", "no", "off"} (case-insensitive); so =0 / =false / =off leave
    validation ON.
    "Off wins": there is no way to force validation on over the env kill switch.
    Otherwise loads the contract and resolver and returns an enforcing runtime.
    """
    if _env_disabled() or not enabled:
        # Pass the path as the label: the factory knows it without parsing the file.
        return ContractRuntime.disabled(str(contract_path))
    contract = Contract.from_yaml(contract_path)
    resolver = Resolver(list(schema_paths))
    return ContractRuntime(contract, resolver)
