# tests/test_schema.py
from pathlib import Path

import pytest

from contract_core.schema import Schema

FIX = Path(__file__).parent / "fixtures" / "schemas"


def test_load_tabular_schema_and_ref():
    s = Schema.from_yaml(FIX / "peec" / "prompts_export" / "1.0.0.yaml")
    assert s.ref == "peec.prompts_export@1.0.0"
    assert s.kind == "tabular"
    assert [f.name for f in s.fields] == ["prompt", "sentiment", "position", "share_of_voice"]


def test_rejects_both_fields_and_json_schema():
    with pytest.raises(ValueError):
        Schema(schema="x.y", version="1.0.0", kind="payload",
               fields=[{"name": "a", "type": "string"}], json_schema={"type": "object"})


def test_json_schema_requires_payload_kind():
    with pytest.raises(ValueError):
        Schema(schema="x.y", version="1.0.0", kind="tabular", json_schema={"type": "object"})


def test_models_do_not_emit_field_shadow_userwarning():
    # §15 item 5: the `schema` field shadowed BaseModel.schema and warned on EVERY import/run,
    # visible to every CLI consumer. Import under -W error::UserWarning must succeed.
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", "-c",
         "import contract_core.schema; import contract_core.contract; import contract_core.cli"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
