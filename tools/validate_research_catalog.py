#!/usr/bin/env python3
"""Validate the checked-in FM20 semantic registry and corpus manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "research" / "registry.json"
CORPUS_PATH = ROOT / "research" / "corpus.json"


class CatalogueError(ValueError):
    """A checked-in catalogue invariant was violated."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CatalogueError(f"{path}: root must be an object")
    return value


def require_unique_ids(items: list[dict[str, Any]], label: str) -> set[str]:
    identifiers = [item.get("id") for item in items]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise CatalogueError(f"{label}: every entry requires a non-empty string id")
    duplicates = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
    if duplicates:
        raise CatalogueError(f"{label}: duplicate ids: {', '.join(duplicates)}")
    return set(identifiers)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate() -> list[str]:
    registry = load_json(REGISTRY_PATH)
    corpus = load_json(CORPUS_PATH)
    if registry.get("schema_version") != 1 or corpus.get("schema_version") != 1:
        raise CatalogueError("registry and corpus must use schema_version 1")

    builds = require_unique_ids(registry.get("builds", []), "builds")
    if corpus.get("build") not in builds:
        raise CatalogueError(f"corpus references unknown build {corpus.get('build')!r}")

    corpus_entries = corpus.get("entries", [])
    entry_ids = require_unique_ids(corpus_entries, "corpus entries")
    capture_ids: set[str] = set()
    missing: list[str] = []
    for entry in corpus_entries:
        unknown_contrasts = set(entry.get("known_contrasts", [])) - entry_ids
        if unknown_contrasts:
            raise CatalogueError(
                f"{entry['id']}: unknown contrasts: {', '.join(sorted(unknown_contrasts))}"
            )
        for capture in entry.get("captures", []):
            capture_id = capture.get("id")
            if not isinstance(capture_id, str) or not capture_id:
                raise CatalogueError(f"{entry['id']}: capture requires an id")
            if capture_id in capture_ids:
                raise CatalogueError(f"duplicate capture id: {capture_id}")
            capture_ids.add(capture_id)
            relative = Path(capture.get("path", ""))
            if relative.is_absolute() or ".." in relative.parts:
                raise CatalogueError(f"{capture_id}: artifact path must be repository-relative")
            artifact = ROOT / relative
            if not artifact.exists():
                missing.append(relative.as_posix())
                continue
            actual = sha256(artifact)
            if actual != capture.get("sha256"):
                raise CatalogueError(
                    f"{capture_id}: SHA-256 mismatch: expected {capture.get('sha256')}, got {actual}"
                )

    confidence = set(registry.get("confidence_order", []))
    evidence_references: set[str] = set()
    for section in (
        "types",
        "object_resolvers",
        "functions",
        "properties",
        "visibility_rules",
        "discoverability_rules",
        "experiments",
    ):
        items = registry.get(section, [])
        require_unique_ids(items, section)
        for item in items:
            if item.get("build") is not None and item["build"] not in builds:
                raise CatalogueError(f"{section}.{item['id']}: unknown build {item['build']}")
            if item.get("confidence") is not None and item["confidence"] not in confidence:
                raise CatalogueError(
                    f"{section}.{item['id']}: unknown confidence {item['confidence']}"
                )
            evidence_references.update(item.get("evidence", []))
    unknown_evidence = evidence_references - capture_ids - entry_ids
    if unknown_evidence:
        raise CatalogueError(
            f"registry references unknown evidence: {', '.join(sorted(unknown_evidence))}"
        )
    return missing


def main() -> int:
    try:
        missing = validate()
    except (CatalogueError, json.JSONDecodeError) as error:
        print(f"INVALID: {error}")
        return 1
    print("VALID: research registry and corpus")
    if missing:
        print(f"INFO: {len(missing)} uncommitted runtime artifact(s) are not present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

