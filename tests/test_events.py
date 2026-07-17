# tests/test_events.py
from contract_core.events import EventLog


def test_emit_and_read_back(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.emit(system="aivx-reports", boundary="peec_prompts",
             schema="peec.prompts_export", version="1.0.0",
             result="pass", observed_shape={"columns": ["prompt"]},
             timestamp="2026-07-16T00:00:00+00:00")
    recs = log.records()
    assert len(recs) == 1
    assert recs[0]["result"] == "pass"
    assert recs[0]["boundary"] == "peec_prompts"
    assert recs[0]["observed_shape"] == {"columns": ["prompt"]}
