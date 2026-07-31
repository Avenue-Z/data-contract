import pytest

from contract_core.scaffold.pyproject import MarkerAction, apply_marker, guard_marker

_MARKER_LINE = '"raw_drift: a drift test guarding a raw boundary (read by `contract reconcile`)"'


def test_rung1_satisfied_when_marker_already_registered():
    text = (
        "[tool.pytest.ini_options]\n"
        'markers = ["raw_drift: already here"]\n'
    )
    assert guard_marker(text) is MarkerAction.SATISFIED


def test_rung2_manual_when_markers_exists_without_raw_drift():
    text = (
        "[tool.pytest.ini_options]\n"
        'markers = ["other: something else"]\n'
    )
    assert guard_marker(text) is MarkerAction.MANUAL


def test_rung3_insert_key_when_section_exists_without_markers():
    text = (
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["src"]\n'
    )
    assert guard_marker(text) is MarkerAction.INSERT_KEY


def test_rung4_append_section_when_absent_entirely():
    text = '[tool.ruff]\nline-length = 100\n'
    assert guard_marker(text) is MarkerAction.APPEND_SECTION


def test_insert_key_places_markers_right_after_the_header():
    text = (
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["src"]\n'
        "\n"
        "[tool.ruff]\n"
    )
    out = apply_marker(text, MarkerAction.INSERT_KEY)
    lines = out.splitlines()
    header_idx = lines.index("[tool.pytest.ini_options]")
    assert lines[header_idx + 1] == f"markers = [{_MARKER_LINE}]"
    assert 'pythonpath = ["src"]' in out
    assert "[tool.ruff]" in out


def test_append_section_adds_a_new_section_at_eof():
    text = "[tool.ruff]\nline-length = 100\n"
    out = apply_marker(text, MarkerAction.APPEND_SECTION)
    assert out.startswith(text.rstrip("\n"))
    assert "[tool.pytest.ini_options]" in out
    assert f"markers = [{_MARKER_LINE}]" in out


def test_apply_marker_refuses_satisfied_and_manual():
    with pytest.raises(ValueError):
        apply_marker("anything", MarkerAction.SATISFIED)
    with pytest.raises(ValueError):
        apply_marker("anything", MarkerAction.MANUAL)


def test_result_of_insert_key_is_itself_satisfied():
    """Round-trip: whatever apply_marker produces, guard_marker reads back as SATISFIED."""
    text = "[tool.pytest.ini_options]\npythonpath = [\"src\"]\n"
    out = apply_marker(text, MarkerAction.INSERT_KEY)
    assert guard_marker(out) is MarkerAction.SATISFIED


def test_result_of_append_section_is_itself_satisfied():
    text = "[tool.ruff]\nline-length = 100\n"
    out = apply_marker(text, MarkerAction.APPEND_SECTION)
    assert guard_marker(out) is MarkerAction.SATISFIED


@pytest.mark.parametrize("header", [
    "[tool.pytest.ini_options]  # pytest config",
    "[tool.pytest.ini_options]# no space",
    "[tool.pytest.ini_options]   ",
])
def test_insert_key_tolerates_comment_and_whitespace_on_header(header):
    """guard_marker classified INSERT_KEY from a tomllib parse; apply_marker located the header
    by exact line equality, so a commented/whitespaced header crashed apply mid-run. Both now
    share one matcher — classify and insert must agree, and the result reads back SATISFIED."""
    text = f"{header}\npythonpath = [\"src\"]\n"
    assert guard_marker(text) is MarkerAction.INSERT_KEY
    out = apply_marker(text, MarkerAction.INSERT_KEY)
    assert guard_marker(out) is MarkerAction.SATISFIED


def test_dotted_inline_ini_options_falls_back_to_manual():
    """A dotted/inline-table spelling has no `[tool.pytest.ini_options]` header LINE to anchor
    the text insert, so guard_marker returns MANUAL rather than crashing in apply_marker."""
    text = '[tool.pytest]\nini_options = {pythonpath = ["src"]}\n'
    assert guard_marker(text) is MarkerAction.MANUAL
