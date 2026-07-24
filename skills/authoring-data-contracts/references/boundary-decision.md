# Boundary decision tree

Work through this once per data source and once per deliverable. It answers three questions:
**which group** (`raw` / `inputs` / `outputs`), **how many boundaries**, and **which `kind`**.

## 1. Is it something you read, or something you emit?

- **Read** (a source you consume) → `inputs` (and maybe `raw`, see step 2).
- **Emit** (a deliverable you produce) → `outputs`.
- **A frame your own code produces and then re-reads?** Model it under `outputs`, not `inputs`.
  Inputs are *open* (extra fields pass silently), so a forgotten column update on a self-produced
  frame is silent. Outputs *warn* on an extra field — which is what you want for your own drift.

## 2. Is the source mediated? → one boundary or two

A **mediated** source is one whose response shape is a function of *your request*, not a fixed
vendor property: an **API, an MCP tool, or an LLM**. A mediated source gets **two** boundaries:

```
vendor ── @runtime.raw("...raw")  ← validates the raw payload AT THE VENDOR EDGE (catches drift)
             │ (per-call-site schema; NOT reused across systems)
          adapter  (a dumb pass-through mapper, separately drift-tested)
             │
          @runtime.input("...")   ← validates the normalized, reusable shape (protects downstream)
```

- The **raw** boundary is what actually catches vendor drift (incident #1). It **has a schema** — a
  per-call-site shape describing the raw payload you depend on. It is not promoted/reused.
- The **input** boundary is the tidy, named, reusable schema the rest of your code (and other
  systems) consume.

A **non-mediated** source — a **file / CSV** whose shape you did not shape by a request — gets a
**single** normalized `input` boundary. No `raw`, no adapter.

> Every `raw` boundary you declare **must** have a companion `@pytest.mark.raw_drift("<name>")` test,
> or `contract reconcile` emits a category-D finding. The adapter must fail on an unknown raw shape —
> an adapter that silently coerces a changed vendor shape into the old schema defeats the whole point.

## 3. Which `kind` — `tabular` or `payload`?

- **`tabular`** — rows and columns (a DataFrame, a CSV, a table). Validated with Pandera.
- **`payload`** — a nested / JSON object (an API body, an LLM result, a report document).
  Validated with Pydantic / jsonschema.

Rule of thumb: if you'd naturally hold it in a DataFrame, it's `tabular`; if it's a dict/JSON
document, it's `payload`.

## 4. What goes where — decorator placement

- `@runtime.raw("name")` decorates the **true raw read** — the `requests.get(...).json()` or
  `pd.read_csv(...)` return, **before** any strip / filter / rename. Decorate a post-cleaning
  function and drift can hide in the cleaning step.
- `@runtime.input("name")` decorates the function that returns the normalized shape (often the
  adapter's output for a mediated source, or the `read_csv` for a file source).
- `@runtime.output("name")` decorates the function that returns the deliverable, **before** it is
  written to its sink. Outputs validate before publish.

## Worked mapping — a mediated + file example

| Source / sink | Group | `kind` | Boundaries |
| --- | --- | --- | --- |
| TikTok Ads API (mediated) | `raw` + `inputs` | payload (raw) + tabular (normalized) | 2 |
| A sentiment CSV export (file) | `inputs` | tabular | 1 |
| The JSON report you emit | `outputs` | payload | 1 |
