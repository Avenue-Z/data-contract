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


def test_major_pin_skips_non_semver_stem():
    # a stray `latest.yaml` in the schema dir must be skipped, not crash
    # major-pin resolution on int("latest").
    r = Resolver([FIX])
    s = r.resolve("peec.prompts_export@1")
    assert s.version == "1.1.0"


def test_missing_schema_raises():
    r = Resolver([FIX])
    with pytest.raises(SchemaNotFound):
        r.resolve("peec.nonexistent@1")


# ---- diagnosing an unsupported pin form (F4) ----
#
# Two pin forms exist: `@MAJOR` (highest matching) and `@X.Y.Z` (exact). Anything with a dot
# is looked up as an exact filename, so the near-universal `@1.0` became a literal
# `1.0.yaml` lookup and failed with a bare "schema missing" even though `1.0.0.yaml` is
# right there — the message misdiagnosed the cause.


def test_minor_pin_error_names_the_supported_forms_and_suggests_the_range_pin():
    r = Resolver([FIX])
    with pytest.raises(SchemaNotFound) as ei:
        r.resolve("peec.prompts_export@1.0")
    msg = str(ei.value)
    assert "peec.prompts_export@1.0" in msg
    assert "@1" in msg and "@1.0.0" in msg      # both supported forms are named
    assert "did you mean" in msg.lower()        # and the range pin is suggested


def test_a_genuinely_missing_schema_does_not_suggest_a_pin_form():
    # The suggestion must not fire when the schema itself is absent — that would swap one
    # misdiagnosis for another.
    r = Resolver([FIX])
    with pytest.raises(SchemaNotFound) as ei:
        r.resolve("peec.nonexistent@1")
    assert "did you mean" not in str(ei.value).lower()


def test_an_unresolvable_exact_version_reports_the_versions_that_exist():
    r = Resolver([FIX])
    with pytest.raises(SchemaNotFound) as ei:
        r.resolve("peec.prompts_export@9.9.9")
    assert "1.0.0" in str(ei.value)


@pytest.mark.parametrize("ref", [
    "peec.prompts_export",       # forgotten pin — at least as common as @1.0
    "peec.prompts_export@",      # the `@` typed, the major forgotten
    "peec.prompts_export@v1",    # a non-numeric major
])
def test_an_unparseable_major_is_a_diagnosis_not_a_valueerror(ref):
    # `int(version)` ran before the diagnosis could, so these escaped as a bare
    # ValueError("invalid literal for int()") that `lint` does not catch — no LINT FAILED
    # header, no ref name, no message at all. A forgotten pin is the likeliest bad pin
    # there is, and it gave the worst output of any of them.
    r = Resolver([FIX])
    with pytest.raises(SchemaNotFound) as ei:
        r.resolve(ref)
    msg = str(ei.value)
    assert ref in msg
    assert "@1" in msg and "@1.0.0" in msg  # both supported forms are named
    assert "available: 1.0.0" in msg        # and the versions that do exist
