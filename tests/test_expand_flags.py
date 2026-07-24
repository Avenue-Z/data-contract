# tests/test_expand_flags.py
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "expand-flags.sh"


def _expand(flag: str, stdin: str) -> list[str]:
    """Run expand-flags.sh and return its NUL-delimited tokens as a list."""
    proc = subprocess.run(
        ["bash", str(SCRIPT), flag],
        input=stdin, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    tokens = proc.stdout.split("\0")
    # A trailing delimiter leaves an empty final element — drop it.
    if tokens and tokens[-1] == "":
        tokens.pop()
    return tokens


def test_multiple_lines_become_repeated_flags():
    assert _expand("--schemas", "schemas\nvendor/schemas\n") == [
        "--schemas", "schemas", "--schemas", "vendor/schemas",
    ]


def test_blank_and_trailing_lines_are_skipped():
    # Load-bearing: a stray blank / trailing line must NOT become --schemas ""
    assert _expand("--schemas", "schemas\n\n\nvendor\n") == [
        "--schemas", "schemas", "--schemas", "vendor",
    ]


def test_whitespace_only_line_is_skipped():
    assert _expand("--tests", "tests\n   \ndrift\n") == [
        "--tests", "tests", "--tests", "drift",
    ]


def test_surrounding_whitespace_is_trimmed():
    # A YAML `|` block preserves trailing spaces; an untrimmed value becomes a
    # non-existent path and reds the gate on a VALID contract — the false red.
    assert _expand("--schemas", "schemas \n  vendor/schemas\t\n") == [
        "--schemas", "schemas", "--schemas", "vendor/schemas",
    ]


def test_empty_input_yields_no_flags():
    assert _expand("--schemas", "") == []
    assert _expand("--schemas", "\n\n") == []


def test_value_with_spaces_survives_as_one_token():
    # NUL delimiting is what makes this safe — a space in a path stays one argv element.
    assert _expand("--schemas", "dir with spaces/schemas\n") == [
        "--schemas", "dir with spaces/schemas",
    ]


def test_missing_flag_arg_is_a_usage_error():
    proc = subprocess.run(["bash", str(SCRIPT)], input="x\n",
                          capture_output=True, text=True)
    assert proc.returncode == 2
