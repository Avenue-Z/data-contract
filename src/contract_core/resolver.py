# src/contract_core/resolver.py
from pathlib import Path

from contract_core.schema import Schema


class SchemaNotFound(KeyError):
    pass


def _parse_semver(v: str) -> tuple[int, int, int]:
    parts = [int(p) for p in v.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


class Resolver:
    def __init__(self, search_paths: list[str | Path]) -> None:
        self.search_paths = [Path(p) for p in search_paths]

    def resolve(self, ref: str) -> Schema:
        name, _, version = ref.partition("@")
        rel = Path(*name.split("."))
        exact = "." in version  # "1.1.0" has dots; "1" does not
        for base in self.search_paths:
            schema_dir = base / rel
            if not schema_dir.is_dir():
                continue
            if exact:
                path = schema_dir / f"{version}.yaml"
                if path.is_file():
                    return Schema.from_yaml(path)
            else:
                major = int(version)
                candidates = [
                    (p, _parse_semver(p.stem))
                    for p in schema_dir.glob("*.yaml")
                    if _parse_semver(p.stem)[0] == major
                ]
                if candidates:
                    best = max(candidates, key=lambda c: c[1])[0]
                    return Schema.from_yaml(best)
        raise SchemaNotFound(ref)
