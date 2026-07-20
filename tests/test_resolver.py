# tests/test_resolver.py
from pathlib import Path

import pytest

from contract_core.resolver import Resolver, SchemaNotFound

FIX = Path(__file__).parent / "fixtures" / "schemas"


def test_exact_version_resolves():
    r = Resolver([FIX])
    s = r.resolve("peec.prompts_export@1.0.0")
    assert s.version == "1.0.0"


def test_major_pin_resolves_to_newest_matching():
    r = Resolver([FIX])
    s = r.resolve("peec.prompts_export@1")
    assert s.version == "1.1.0"  # newest with major 1


def test_missing_schema_raises():
    r = Resolver([FIX])
    with pytest.raises(SchemaNotFound):
        r.resolve("peec.nonexistent@1")
