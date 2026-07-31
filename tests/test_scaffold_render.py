import pytest

from contract_core.scaffold.render import render


@pytest.fixture
def _fixture_template(tmp_path, monkeypatch):
    """Point render() at a throwaway templates dir so this test has no dependency on the real
    package templates (Task 3), which do not exist yet when this task is implemented."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "greeting.txt.tmpl").write_text("Hello {{NAME}}, welcome to {{PLACE}}.\n")
    (templates_dir / "with_braces.txt.tmpl").write_text("dict: {kind: {{KIND}}}\n")
    monkeypatch.setattr("contract_core.scaffold.render._TEMPLATES_DIR", templates_dir)
    return templates_dir


def test_render_substitutes_every_placeholder(_fixture_template):
    out = render("greeting.txt.tmpl", {"NAME": "Ada", "PLACE": "the scaffold"})
    assert out == "Hello Ada, welcome to the scaffold.\n"


def test_render_does_not_use_str_format_so_literal_braces_survive(_fixture_template):
    # A literal YAML/dict brace in the template (e.g. `{kind: api}`) must NOT be mistaken for a
    # substitution token — .replace(), not .format(), is required (conftest.py's own convention).
    out = render("with_braces.txt.tmpl", {"KIND": "api"})
    assert out == "dict: {kind: api}\n"


def test_render_missing_template_raises_filenotfounderror(_fixture_template):
    with pytest.raises(FileNotFoundError):
        render("does_not_exist.tmpl", {})
