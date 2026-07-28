# tests/test_events_report.py
from contract_core.contract import Contract
from contract_core.events_report import read_records, render_human, summarize


def rec(*, system="demo", boundary="prompts", schema="peec.prompts_export",
        version="1.0.0", result="pass", shape=None):
    return {
        "system": system, "boundary": boundary, "schema": schema, "version": version,
        "result": result, "observed_shape": shape or {"columns": ["a"], "dtypes": {"a": "object"}},
        "timestamp": "2026-07-28T00:00:00Z",
    }


def _write(path, lines):
    path.write_text("".join(line + "\n" for line in lines))
    return path


# ---- read_records ----

def test_read_records_reads_valid_lines(tmp_path):
    import json
    p = _write(tmp_path / "e.jsonl", [json.dumps(rec()), json.dumps(rec(result="warn"))])
    records, skipped = read_records(p)
    assert len(records) == 2
    assert skipped == 0


def test_read_records_tolerates_truncated_final_line(tmp_path):
    import json
    p = tmp_path / "e.jsonl"
    p.write_text(json.dumps(rec()) + "\n" + '{"system": "demo", "bou')  # crashed mid-write
    records, skipped = read_records(p)
    assert len(records) == 1
    assert skipped == 1


def test_read_records_does_not_count_blank_lines(tmp_path):
    import json
    p = tmp_path / "e.jsonl"
    p.write_text(json.dumps(rec()) + "\n\n   \n")
    records, skipped = read_records(p)
    assert len(records) == 1
    assert skipped == 0


def test_read_records_missing_path_is_empty(tmp_path):
    records, skipped = read_records(tmp_path / "nope.jsonl")
    assert records == []
    assert skipped == 0


def test_read_records_directory_raises_oserror(tmp_path):
    import pytest
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(OSError):
        read_records(d)


# ---- summarize: verdicts ----

def test_verdict_clean_when_all_pass():
    report = summarize([rec(result="pass"), rec(result="pass")])
    b = report.systems[0].boundaries[0]
    assert b.verdict == "clean"
    assert (b.events, b.n_pass, b.n_warn, b.n_violation) == (2, 2, 0, 0)


def test_verdict_review_when_warn_no_violation():
    report = summarize([rec(result="pass"), rec(result="warn")])
    assert report.systems[0].boundaries[0].verdict == "review"


def test_verdict_blocked_when_any_violation():
    report = summarize([rec(result="pass"), rec(result="warn"), rec(result="violation")])
    b = report.systems[0].boundaries[0]
    assert b.verdict == "blocked"
    assert b.n_violation == 1


def test_result_mapping_is_pinned_to_runtime_invariant():
    # A violation dominates a warn (violation would hard-fail under enforce, runtime.py:149-166).
    mixed = summarize([rec(result="warn"), rec(result="violation")])
    assert mixed.systems[0].boundaries[0].verdict == "blocked"
    # warn alone never reads as blocked (a warn does not hard-fail).
    assert summarize([rec(result="warn")]).systems[0].boundaries[0].verdict == "review"


def test_last_shape_is_last_record_in_file_order():
    first = {"columns": ["a"], "dtypes": {"a": "object"}}
    last = {"columns": ["a", "b"], "dtypes": {"a": "object", "b": "float64"}}
    report = summarize([rec(shape=first), rec(shape=last)])
    assert report.systems[0].boundaries[0].last_shape == last


# ---- summarize: grouping / drift ----

def test_drift_produces_two_distinct_rows():
    report = summarize([rec(version="1.0.0"), rec(version="1.2.0")])
    versions = sorted(b.version for b in report.systems[0].boundaries)
    assert versions == ["1.0.0", "1.2.0"]


def test_multi_system_one_global_summary():
    report = summarize([rec(system="a", result="pass"), rec(system="b", result="violation")])
    assert {s.system for s in report.systems} == {"a", "b"}
    # one global summary aggregating across systems
    assert report.summary["clean"] == 1
    assert report.summary["blocked"] == 1
    assert report.summary["ready"] is False


# ---- summarize: unobserved (requires contract, scoped to system) ----

def _contract(system="demo", names_to_refs=None):
    names_to_refs = names_to_refs or {"prompts": "peec.prompts_export@1"}
    return Contract.model_validate({
        "system": system, "version": "1.0.0",
        "inputs": [{"name": n, "schema": r} for n, r in names_to_refs.items()],
    })


def test_unobserved_flags_declared_but_unfired():
    c = _contract(names_to_refs={"prompts": "peec.prompts_export@1",
                                 "team_capacity": "sentiment.capacity@1"})
    report = summarize([rec(boundary="prompts")], contract=c)
    unobs = report.systems[0].unobserved
    assert [u.boundary for u in unobs] == ["team_capacity"]
    # declared pin, not a resolved version
    assert (unobs[0].schema, unobs[0].version) == ("sentiment.capacity", "1")


def test_unobserved_none_without_contract():
    report = summarize([rec(boundary="prompts")])
    assert all(sr.unobserved == [] for sr in report.systems)


def test_unobserved_scoped_to_contract_system():
    # 'report' fired only under system B; the contract is for system A → A's 'report' is unobserved.
    c = _contract(system="A", names_to_refs={"report": "aivx.report@1"})
    report = summarize([rec(system="B", boundary="report")], contract=c)
    a = next(sr for sr in report.systems if sr.system == "A")
    assert [u.boundary for u in a.unobserved] == ["report"]


def test_unobserved_matches_by_name_stale_ref_stays_observed():
    # contract declares prompts@2 but the log has only prompts@1 events → observed by name.
    c = _contract(names_to_refs={"prompts": "peec.prompts_export@2"})
    report = summarize([rec(boundary="prompts", version="1.0.0")], contract=c)
    sr = next(s for s in report.systems if s.system == "demo")
    assert sr.unobserved == []


# ---- ready / skipped ----

def test_ready_true_only_when_no_blocked_and_no_unobserved():
    assert summarize([rec(result="pass")]).summary["ready"] is True
    assert summarize([rec(result="violation")]).summary["ready"] is False
    c = _contract(names_to_refs={"prompts": "peec.prompts_export@1", "x": "p.x@1"})
    # 'x' is declared but never fired → unobserved → not ready
    assert summarize([rec(boundary="prompts")], contract=c).summary["ready"] is False


def test_skipped_threads_into_summary():
    assert summarize([rec()], skipped=3).summary["skipped"] == 3


# ---- render (human) ----

def test_human_render_drift_rows_are_distinguishable():
    out = render_human(summarize([rec(version="1.0.0"), rec(version="1.2.0")]))
    assert "@1.0.0" in out
    assert "@1.2.0" in out  # the render must NOT collapse both to @1


def test_human_render_observed_full_version_unobserved_pin():
    c = _contract(names_to_refs={"prompts": "peec.prompts_export@1",
                                 "team_capacity": "sentiment.capacity@1"})
    out = render_human(summarize([rec(boundary="prompts", version="1.0.0")], contract=c))
    assert "peec.prompts_export@1.0.0" in out       # observed → resolved version
    assert "sentiment.capacity@1" in out            # unobserved → declared pin
    assert "unobserved" in out


# ---- round-four review: fail-closed on no/absent/malformed evidence ----

def test_ready_false_when_no_boundaries_observed():
    # #1 ship-blocker: an empty log must NOT read as ready — zero evidence != safe.
    assert summarize([]).summary["ready"] is False


def test_read_records_skips_non_dict_json_lines(tmp_path):
    # #2: valid JSON that isn't an object (scalar/array) must be skipped, not crash summarize.
    p = tmp_path / "e.jsonl"
    p.write_text("123\n[1, 2]\n\"x\"\n")
    records, skipped = read_records(p)
    assert records == []
    assert skipped == 3


def test_read_records_skips_records_missing_required_keys(tmp_path):
    import json
    p = tmp_path / "e.jsonl"
    p.write_text(json.dumps({"system": "s"}) + "\n")  # missing boundary/schema/version/result/shape
    records, skipped = read_records(p)
    assert (records, skipped) == ([], 1)


def test_read_records_skips_record_with_non_dict_observed_shape(tmp_path):
    import json
    p = tmp_path / "e.jsonl"
    p.write_text(json.dumps(rec(shape=None) | {"observed_shape": "oops"}) + "\n")
    records, skipped = read_records(p)
    assert (records, skipped) == ([], 1)


def test_summarize_does_not_crash_and_flags_unknown_result():
    # #3: a parseable record with an unrecognized result must NOT read as clean/ready.
    r = rec(result="banana")
    report = summarize([r])
    b = report.systems[0].boundaries[0]
    assert b.verdict != "clean"
    assert report.summary["ready"] is False


def test_human_clean_row_has_no_counts_and_boundary_before_ref():
    # #4: match the approved §4 mockup — boundary before ref, no counts on clean rows.
    out = render_human(summarize([rec(result="pass")]))
    row = next(line for line in out.splitlines() if "[clean]" in line)
    assert "pass" not in row  # clean rows carry no (n pass, ...) breakdown
    assert row.index("prompts") < row.index("peec.prompts_export")


def test_human_summary_line_matches_mockup():
    out = render_human(summarize([rec(result="violation")]))
    assert out.splitlines()[-1] == "Not ready: 1 blocked, 0 unobserved. 0 clean, 0 needs review."


def test_unobserved_refless_schema_has_no_dangling_at():
    # #6: a contract ref with no @major must not render "foo@".
    c = Contract.model_validate({"system": "demo", "version": "1.0.0",
                                 "inputs": [{"name": "x", "schema": "foo"}]})
    out = render_human(summarize([], contract=c))
    assert "foo@" not in out


def test_read_records_skips_record_with_non_string_grouping_field(tmp_path):
    # #1: a valid-JSON record whose grouping field isn't a str would make the (system, boundary,
    # schema, version) key unhashable and crash summarize — read_records must reject it.
    import json
    bad = {"system": ["a"], "boundary": "x", "schema": "y", "version": "z",
           "result": "pass", "observed_shape": {}}
    p = tmp_path / "e.jsonl"
    p.write_text(json.dumps(bad) + "\n")
    records, skipped = read_records(p)
    assert (records, skipped) == ([], 1)


def test_read_records_output_never_crashes_summarize_on_foreign_input(tmp_path):
    # The pipeline guarantee: whatever read_records returns, summarize does not raise.
    import json
    lines = ["123", '{"system": ["a"], "boundary": "x", "schema": "y", "version": "z", '
             '"result": "pass", "observed_shape": {}}', json.dumps({"nope": 1})]
    p = tmp_path / "e.jsonl"
    p.write_text("\n".join(lines) + "\n")
    records, skipped = read_records(p)
    summarize(records, skipped=skipped)  # must not raise
    assert records == []
    assert skipped == 3
