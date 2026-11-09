"""Validate the machine-readable research source and model registries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REGISTRY = ROOT / "data" / "source_registry.json"
MODEL_REGISTRY = ROOT / "data" / "model_registry.json"

SOURCE_FIELDS = {
    "id", "name", "kind", "status", "scope", "variables",
    "temporal_coverage", "spatial_resolution", "uncertainty",
    "limitations", "license", "reference_urls", "dependency_group", "use",
}
MODEL_FIELDS = {"id", "name", "implementation", "current_status", "target_role",
                "known_limitations", "production_eligible"}


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Registry file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Registry root must be an object: {path}")
    return value


def _check_unique(records: list[dict[str, Any]], label: str) -> None:
    ids = [item.get("id") for item in records]
    if any(not isinstance(value, str) or not value.strip() for value in ids):
        raise ValueError(f"{label}: each record needs a non-empty string id")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label}: duplicate ids found")


def validate_registries(
    source_path: Path = SOURCE_REGISTRY,
    model_path: Path = MODEL_REGISTRY,
) -> dict[str, int]:
    sources_doc = _load(source_path)
    models_doc = _load(model_path)

    sources = sources_doc.get("sources")
    legacy = models_doc.get("legacy_models")
    candidates = models_doc.get("candidate_models")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Source registry must contain a non-empty 'sources' array")
    if not isinstance(legacy, list) or not legacy:
        raise ValueError("Model registry must contain a non-empty 'legacy_models' array")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Model registry must contain a non-empty 'candidate_models' array")

    _check_unique(sources, "sources")
    _check_unique(legacy, "legacy_models")
    _check_unique(candidates, "candidate_models")

    for item in sources:
        missing = SOURCE_FIELDS - item.keys()
        if missing:
            raise ValueError(f"Source {item.get('id')}: missing fields {sorted(missing)}")
        if not item["reference_urls"] or not item["limitations"]:
            raise ValueError(f"Source {item['id']}: references and limitations must be explicit")
        if not item["dependency_group"]:
            raise ValueError(f"Source {item['id']}: dependency_group must be explicit")

    for item in legacy:
        missing = MODEL_FIELDS - item.keys()
        if missing:
            raise ValueError(f"Legacy model {item.get('id')}: missing fields {sorted(missing)}")

    legacy_ids = {item["id"] for item in legacy}
    if not {"K0", "K1", "K2", "K3", "K4"}.issubset(legacy_ids):
        raise ValueError("Legacy registry must declare K0, K1, K2, K3 and K4")

    # Legacy K0-K4 are audit/benchmark modules until the new evaluation gates pass.
    unsafe = [
        item["id"] for item in legacy
        if item.get("production_eligible") is not False
    ]
    if unsafe:
        raise ValueError(f"Legacy models cannot be production eligible: {unsafe}")

    rules = models_doc.get("combination_rules", {})
    if rules.get("never_add_probabilities") is not True:
        raise ValueError("Combination rules must prohibit direct probability addition")
    if rules.get("missing_required_physical_input") is None:
        raise ValueError("Missing physical input policy must be explicit")
    if rules.get("source_quality_scores_do_not_directly_subtract_from_probability") is not True:
        raise ValueError("Source quality score must not directly subtract from probability")

    return {
        "sources": len(sources),
        "legacy_models": len(legacy),
        "candidate_models": len(candidates),
    }


if __name__ == "__main__":
    counts = validate_registries()
    print(
        "Registry validation passed: "
        f"{counts['sources']} sources, {counts['legacy_models']} legacy models, "
        f"{counts['candidate_models']} candidate models."
    )
