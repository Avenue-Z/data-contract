# src/contract_core/resolver.py
from pathlib import Path

from contract_core.schema import Schema


class SchemaNotFound(KeyError):
    pass


def parse_semver(v: str) -> tuple[int, int, int] | None:
    """Parse a semver stem, or return None for a non-versioned filename.

    Returning None (rather than raising) lets the major-pin glob skip stray
    files like `latest.yaml` or `_template.yaml` instead of crashing on them.

    Public (no leading underscore) because "what stem counts as a schema file" is now a
    contract shared with `cli._lintable_schema_files`, not a resolver-private detail:
    lint must consider exactly the files the resolver would, and no others.
    """
    try:
        parts = [int(p) for p in v.split(".")]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


# There are exactly two pin forms, and `@1.0` is not one of them (see `_is_partial_pin`).
_PIN_FORMS = "@MAJOR for the highest match (e.g. @1), or @MAJOR.MINOR.PATCH exact (e.g. @1.0.0)"


def _is_partial_pin(version: str) -> bool:
    """Is this a dotted pin with fewer than three parts — the `@1.0` convention we don't take?

    `resolve` routes any ref containing a dot to an exact filename lookup, so `@1.0` looks
    for a literal `1.0.yaml` and misses `1.0.0.yaml` sitting beside it. The form is a
    near-universal habit, so the failure needs to name itself rather than surface as a bare
    "schema missing" — which diagnoses the wrong problem entirely.
    """
    parts = version.split(".")
    return 1 < len(parts) < 3 and all(p.isdigit() for p in parts)


class Resolver:
    def __init__(self, search_paths: list[str | Path]) -> None:
        self.search_paths = [Path(p) for p in search_paths]

    def resolve(self, ref: str) -> Schema:
        name, _, version = ref.partition("@")
        rel = Path(*name.split("."))
        exact = "." in version  # "1.1.0" has dots; "1" does not
        searched: list[Path] = []
        for base in self.search_paths:
            schema_dir = base / rel
            if not schema_dir.is_dir():
                continue
            searched.append(schema_dir)
            if exact:
                path = schema_dir / f"{version}.yaml"
                if path.is_file():
                    return Schema.from_yaml(path)
            elif version.isdigit():
                # Guarded, not assumed: `int(version)` ran before `_not_found` could, so a
                # forgotten pin ("s.tab") or a non-numeric major ("@v1") escaped as a bare
                # ValueError that `lint` does not catch. A non-major pin now simply matches
                # nothing and falls through to the diagnosis below.
                major = int(version)
                parsed = ((p, parse_semver(p.stem)) for p in schema_dir.glob("*.yaml"))
                candidates = [(p, v) for p, v in parsed if v is not None and v[0] == major]
                if candidates:
                    best = max(candidates, key=lambda c: c[1])[0]
                    return Schema.from_yaml(best)
        raise SchemaNotFound(self._not_found(ref, name, version, searched))

    def _not_found(self, ref: str, name: str, version: str, searched: list[Path]) -> str:
        """Say which of the four ways this failed, so the reader fixes the right thing.

        One line on purpose: `SchemaNotFound` subclasses `KeyError`, whose `str()` is the
        repr of its argument, so an embedded newline renders as a literal `\\n`.
        """
        if not searched:
            where = ", ".join(str(p) for p in self.search_paths) or "<no search paths>"
            return f"{ref} — no directory for schema {name!r} under: {where}"
        # Sort by the parsed (major, minor, patch), not the stem: a plain string sort puts
        # 10.0.0 before 2.0.0, misleading on a message whose job is to help pick a version (#55).
        parsed = {p.stem: v for d in searched for p in d.glob("*.yaml")
                  if (v := parse_semver(p.stem)) is not None}
        available = sorted(parsed, key=lambda s: parsed[s])
        have = f"available: {', '.join(available)}" if available else "no versioned files there"
        if _is_partial_pin(version):
            return (f"{ref} — no file {version}.yaml; pin forms are {_PIN_FORMS}. "
                    f"Did you mean @{version.split('.')[0]}? ({have})")
        if "." not in version and not version.isdigit():
            what = "no version pin" if not version else f"{version!r} is not a numeric major"
            return f"{ref} — {what}; pin forms are {_PIN_FORMS}. ({have})"
        missing = (f"no file {version}.yaml" if "." in version
                   else f"no version {version}.x.x")
        return f"{ref} — {missing}; {have}"
