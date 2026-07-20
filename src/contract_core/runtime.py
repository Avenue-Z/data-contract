# src/contract_core/runtime.py
import functools
from collections.abc import Callable

import pandas as pd
import pandera.pandas as pa

from contract_core.compile.jsonschema_compile import to_json_schema
from contract_core.compile.pandera_compile import to_pandera
from contract_core.contract import BoundarySpec, Contract
from contract_core.errors import ContractViolation, FieldDiff
from contract_core.events import EventLog
from contract_core.resolver import Resolver
from contract_core.schema import Schema


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

    def _spec(self, direction: str, name: str) -> BoundarySpec:
        group = {"raw": self.contract.raw, "input": self.contract.inputs,
                 "output": self.contract.outputs}[direction]
        for b in group:
            if b.name == name:
                return b
        raise KeyError(f"no {direction} boundary named {name!r} in contract")

    def raw(self, name: str):
        return self._decorator("raw", name)

    def input(self, name: str):
        return self._decorator("input", name)

    def output(self, name: str):
        return self._decorator("output", name)

    def _decorator(self, direction: str, name: str):
        spec = self._spec(direction, name)
        resolved = self.resolver.resolve(spec.schema)
        ContractRuntime.REGISTRY.append((direction, name))

        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                data = fn(*args, **kwargs)
                self._validate(direction, spec, resolved, data)
                return data
            return wrapper
        return deco

    # ---- validation ----

    def _validate(self, direction: str, spec: BoundarySpec, resolved: Schema, data) -> None:
        is_output = direction == "output"
        if resolved.kind == "tabular":
            diffs, observed = self._validate_tabular(resolved, data, is_output)
        else:
            diffs, observed = self._validate_payload(resolved, data, is_output)

        hard = [d for d in diffs if d.problem in ("missing", "retyped")]
        extra = [d for d in diffs if d.problem == "extra"]

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

    def _validate_tabular(self, resolved: Schema, df: pd.DataFrame, is_output: bool):
        observed = {"columns": list(df.columns),
                    "dtypes": {c: str(t) for c, t in df.dtypes.items()}}
        diffs: list[FieldDiff] = []
        ps = to_pandera(resolved, strict=False)
        try:
            ps.validate(df, lazy=True)
        except pa.errors.SchemaErrors as err:
            for _, row in err.failure_cases.iterrows():
                check = str(row.get("check", ""))
                if check == "column_in_dataframe":
                    # missing required column: name is in `failure_case`, not `column`.
                    field = str(row.get("failure_case"))
                    problem = "missing"
                    observed = "absent"
                else:
                    # a dtype/value check on a present column: name is in `column`.
                    col = row.get("column")
                    if col is None or (isinstance(col, float) and pd.isna(col)):
                        continue
                    field = str(col)
                    problem = "retyped"
                    observed = str(df.dtypes.get(field, "absent"))
                declared = next((f for f in resolved.fields if f.name == field), None)
                expected = declared.type if declared else "?"
                diffs.append(FieldDiff(field=field, expected=str(expected),
                                       observed=observed, problem=problem))
        # de-dup by field
        seen = {}
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

    def _validate_payload(self, resolved: Schema, payload: dict, is_output: bool):
        import jsonschema
        observed = {"keys": list(payload.keys())}
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
                    if resolved.json_schema else {f.name for f in resolved.fields}
                for k in payload:
                    if k not in declared:
                        diffs.append(FieldDiff(field=str(k), expected="absent",
                                               observed=type(payload[k]).__name__,
                                               problem="extra"))
        return diffs, observed
