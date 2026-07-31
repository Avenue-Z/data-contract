import pytest

from contract_core.scaffold.detect import PackageDetectionError, detect_package


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_flat_layout_is_detected(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    _write(tmp_path, "my_pkg/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.name == "my_pkg"
    assert result.package_dir == tmp_path / "my_pkg"


def test_src_layout_is_detected(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    _write(tmp_path, "src/my_pkg/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.name == "my_pkg"
    assert result.package_dir == tmp_path / "src" / "my_pkg"


def test_hyphenated_project_name_normalizes_to_underscore(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "tiktok-brand-pulse"\n')
    _write(tmp_path, "tiktok_brand_pulse/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.name == "tiktok_brand_pulse"


def test_package_override_skips_name_derivation(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "irrelevant"\n')
    _write(tmp_path, "actual_pkg/__init__.py", "")
    result = detect_package(tmp_path, "actual_pkg")
    assert result.name == "actual_pkg"


def test_missing_pyproject_toml_is_fatal_and_names_package_flag(tmp_path):
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_unparseable_pyproject_toml_is_fatal(tmp_path):
    _write(tmp_path, "pyproject.toml", "not valid toml [[[")
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_no_project_name_and_no_override_is_fatal(tmp_path):
    _write(tmp_path, "pyproject.toml", "[tool.other]\nx = 1\n")
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_neither_layout_present_is_fatal(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_both_layouts_present_is_fatal_and_names_both_paths(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    flat = _write(tmp_path, "my_pkg/__init__.py", "")
    src = _write(tmp_path, "src/my_pkg/__init__.py", "")
    with pytest.raises(PackageDetectionError) as ei:
        detect_package(tmp_path, None)
    assert str(flat) in str(ei.value)
    assert str(src) in str(ei.value)


def test_pyproject_text_is_returned_for_reuse_by_the_marker_guard(tmp_path):
    text = '[project]\nname = "my-pkg"\n'
    _write(tmp_path, "pyproject.toml", text)
    _write(tmp_path, "my_pkg/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.pyproject_text == text
