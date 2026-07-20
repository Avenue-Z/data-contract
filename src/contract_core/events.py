# src/contract_core/events.py
import json
import os
from pathlib import Path
from typing import Any, Literal

Result = Literal["pass", "warn", "violation"]


class EventLog:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = os.environ.get("CONTRACT_EVENT_LOG", "./contract-events.jsonl")
        self.path = Path(path)

    def emit(self, *, system: str, boundary: str, schema: str, version: str,
             result: Result, observed_shape: dict[str, Any], timestamp: str) -> None:
        record = {
            "system": system, "boundary": boundary, "schema": schema,
            "version": version, "result": result,
            "observed_shape": observed_shape, "timestamp": timestamp,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
