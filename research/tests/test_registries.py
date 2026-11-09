from research.validate_registries import validate_registries


def test_source_and_model_registries_are_valid():
    counts = validate_registries()
    assert counts["sources"] >= 10
    assert counts["legacy_models"] == 5
    assert counts["candidate_models"] >= 5
