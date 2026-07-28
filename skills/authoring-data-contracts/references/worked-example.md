# Worked example — `tiktok-brand-pulse`, end to end

A mediated automation (TikTok Ads API → normalized table → JSON report) authored with this skill.
Every file below was linted and reconciled green (output at the bottom). Copy the shape, not the
column names.

## Boundaries (Phase A)

| Source / sink | Group | kind | Why |
| --- | --- | --- | --- |
| TikTok Ads API (mediated) | `raw` + `inputs` | payload (raw) + tabular (normalized) | mediated → two boundaries |
| the JSON report emitted | `outputs` | payload | a deliverable we control |

## Files

```
contract.yaml
schemas/
  tiktok/raw_report/1.0.0.yaml          # raw, per-call-site (payload, json_schema body)
  tiktok/campaign_metrics/1.0.0.yaml    # normalized (tabular)
  brandpulse/report/1.0.0.yaml          # deliverable (payload, fields body)
brand_pulse/
  __init__.py                           # imports boundaries so they register at import time
  boundaries.py                         # load_runtime + the 3 decorators + absent-library fallback
tests/
  test_drift.py                         # @pytest.mark.raw_drift("tiktok_raw")
```

### `contract.yaml`
Modes are shown at `enforce` — the *end* state, after the observe→enforce promotion below. A new
automation starts every boundary at `mode: observe` (as the templates ship) and promotes once the
shape is confirmed on live data.
```yaml
system: tiktok-brand-pulse
version: 1.0.0
raw:
  - name: tiktok_raw
    schema: tiktok.raw_report@1
    source: {kind: api, format: json}
    mode: enforce
inputs:
  - name: campaign_metrics
    schema: tiktok.campaign_metrics@1
    source: {kind: api, format: json}
    mode: enforce
outputs:
  - name: report
    schema: brandpulse.report@1
    sink: {kind: file, format: json}
    mode: enforce
```

### `schemas/tiktok/raw_report/1.0.0.yaml` — the raw shape IS schema'd
A nested raw payload uses the `json_schema:` body (only valid on `kind: payload`). Declare only the
keys the code depends on — this is what catches vendor drift.
```yaml
schema: tiktok.raw_report
version: 1.0.0
kind: payload
json_schema:
  type: object
  required: [code, data]
  properties:
    code: {type: integer}
    data:
      type: object
      required: [list]
      properties:
        list: {type: array}
```

### `schemas/tiktok/campaign_metrics/1.0.0.yaml` — normalized (tabular)
```yaml
schema: tiktok.campaign_metrics
version: 1.0.0
kind: tabular
fields:
  - name: campaign_id
    type: string
    required: true
  - name: spend
    type: float
    required: true
    nullable: false
  - name: impressions
    type: int
    required: true
    nullable: false
  - name: date
    type: string
    required: true
```

### `schemas/brandpulse/report/1.0.0.yaml` — deliverable (payload, flat fields)
```yaml
schema: brandpulse.report
version: 1.0.0
kind: payload
fields:
  - name: brand
    type: string
    required: true
    min_length: 1
  - name: pulse_score
    type: float
    required: true
    minimum: 0.0
    maximum: 1.0
  - name: window
    type: string
    required: true
```

### `brand_pulse/boundaries.py`
```python
from __future__ import annotations
from pathlib import Path

try:
    from contract_core import load_runtime
    _HERE = Path(__file__).resolve()
    # Walk up to the dir holding contract.yaml — works for a flat OR a src/ layout.
    _ROOT = next((p for p in _HERE.parents if (p / "contract.yaml").exists()), None)
    if _ROOT is None:
        raise FileNotFoundError(f"contract.yaml not found in any parent of {_HERE}")
    runtime = load_runtime(str(_ROOT / "contract.yaml"),
                           schema_paths=[str(_ROOT / "schemas")])
except ImportError:                         # §4 absent-library fallback — imports nothing from the lib
    class _NoOpRuntime:
        def _passthrough(self, name):
            return lambda fn: fn
        raw = input = output = _passthrough
    runtime = _NoOpRuntime()


@runtime.raw("tiktok_raw")                  # the TRUE raw read — unmodified vendor payload
def pull_raw(client, **params) -> dict:
    return client.get("/report/integrated/get/", params=params)


@runtime.input("campaign_metrics")          # the adapter — a dumb mapper, drift-tested
def normalize(raw: dict):
    import pandas as pd
    rows = [{"campaign_id": str(i["dimensions"]["campaign_id"]),
             "spend": float(i["metrics"]["spend"]),
             "impressions": int(i["metrics"]["impressions"]),
             "date": str(i["dimensions"]["stat_time_day"])}
            for i in raw["data"]["list"]]
    return pd.DataFrame(rows)


@runtime.output("report")                   # validated BEFORE it is written to its sink
def build_report(df, *, brand: str, window: str) -> dict:
    eff = df["impressions"].sum() / max(df["spend"].sum(), 1.0)
    return {"brand": brand, "pulse_score": round(eff / (eff + 1000.0), 4), "window": window}
```

### `brand_pulse/__init__.py`
```python
from brand_pulse import boundaries as boundaries  # noqa: F401  (registers the boundaries)
```

### `tests/test_drift.py`
```python
import pytest
from brand_pulse.boundaries import normalize

@pytest.mark.raw_drift("tiktok_raw")        # name MUST equal the raw boundary in contract.yaml
def test_adapter_rejects_unknown_raw_shape():
    changed = {"data": {"list": [{"dimensions": {}, "metrics": {}}]}}
    with pytest.raises((KeyError, ValueError, TypeError)):
        normalize(changed)
```

## Verify (Phase C)

```console
$ contract lint --contract contract.yaml --schemas schemas
OK: tiktok-brand-pulse@1.0.0 — 3 boundaries resolved      # exit 0

$ contract reconcile --contract contract.yaml --package brand_pulse --tests tests
OK: tiktok-brand-pulse@1.0.0 — 3 boundaries reconciled     # exit 0
```

Proof the drift gate bites — delete `tests/test_drift.py` and reconcile fails category-D:

```console
$ contract reconcile --contract contract.yaml --package brand_pulse --tests tests
RECONCILE FAILED:
  - raw boundary 'tiktok_raw' declared but no drift test found     # exit 1
```

Then adopt on live data in `observe`, review readiness with `contract events --contract contract.yaml`
(promote a boundary once it reads `clean`, or `review` after reconciling the warn), and flip each
boundary to `enforce`.
