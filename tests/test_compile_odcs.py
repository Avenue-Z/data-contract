# tests/test_compile_odcs.py
from pathlib import Path

import jsonschema
import pytest

from contract_core.compile.odcs import to_odcs, validate_odcs
from contract_core.contract import Contract
from contract_core.resolver import Resolver

FIX = Path(__file__).parent / "fixtures"


def test_odcs_document_is_valid_and_inlines_schemas():
    contract = Contract(
        system="demo", version="1.0.0",
        inputs=[{"name": "prompts", "schema": "peec.prompts_export@1.0.0",
                 "source": {"kind": "file", "format": "csv"}}],
    )
    resolver = Resolver([FIX / "schemas"])
    doc = to_odcs(contract, resolver)
    assert doc["kind"] == "DataContract"
    assert doc["version"] == "1.0.0"
    # the resolved schema's fields are inlined as ODCS properties
    names = [p["name"] for s in doc["schema"] for p in s["properties"]]
    assert "prompt" in names
    validate_odcs(doc)  # must not raise


def test_validate_odcs_rejects_malformed():
    with pytest.raises(jsonschema.ValidationError):
        validate_odcs({"not": "an odcs document"})
