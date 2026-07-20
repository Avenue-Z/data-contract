# src/contract_core/families.py
"""Logical-type-family matching for tabular validation (R8).

`to_pandera` used to compile each logical `type` to one physical pandas dtype and
demand equality under `coerce=False`. That false-fails semantically-valid data
whenever pandas *infers* an equivalent-but-different physical dtype (an `int64`
column for a declared `float`, a nullable int read as `float64`, `object` vs `str`
across pandas 2<->3, an all-null column as `object`).

`dtype_satisfies` replaces exact-dtype equality with a family check that is
non-mutating (it inspects, never coerces) and still rejects a genuine type change
(a stringified number, a real-decimal float where an int was declared) so success
criterion #1 keeps holding.
"""
import pandas as pd
import pandas.api.types as pdt


def dtype_satisfies(field_type: str, series: pd.Series) -> bool:
    """Does `series`'s physical dtype satisfy the declared logical `field_type`?

    Non-null-aware: an all-null column satisfies any type (its dtype is
    uninformative; the ``nullable`` flag enforces null-tolerance separately).
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return True

    if field_type == "string":
        if pdt.is_object_dtype(series):
            # object dtype carries no content guarantee (a column of ints/dicts
            # is still `object`); inspect elements the way the numeric branches
            # do, so a genuine non-string drift declared `string` is rejected.
            return bool(non_null.map(lambda x: isinstance(x, str)).all())
        return bool(pdt.is_string_dtype(series))
    if field_type == "bool":
        return bool(pdt.is_bool_dtype(series))
    if field_type in ("date", "datetime"):
        return bool(pdt.is_datetime64_any_dtype(series))
    if field_type == "float":
        # any numeric dtype widens to float losslessly; bool is numeric in numpy.
        return pdt.is_numeric_dtype(series) and not pdt.is_bool_dtype(series)
    if field_type == "int":
        if pdt.is_bool_dtype(series):
            return False
        if pdt.is_integer_dtype(series):
            return True
        if pdt.is_float_dtype(series):
            # a nullable int read from CSV upcasts to float64 on its NaNs; accept
            # whole-number floats, reject real decimals (a narrowing drift).
            return bool((non_null % 1 == 0).all())
        return False
    return False
