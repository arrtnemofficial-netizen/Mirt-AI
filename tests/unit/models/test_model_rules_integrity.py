from pathlib import Path

import yaml


def test_model_rules_yaml_integrity():
    rules_path = Path(__file__).parents[3] / "data" / "vision" / "generated" / "model_rules.yaml"

    with open(rules_path, encoding="utf-8") as f:
        rules = yaml.safe_load(f)

    assert isinstance(rules, dict)
    model_rules = rules.get("MODEL_RULES")
    assert isinstance(model_rules, dict)
    assert len(model_rules) > 0

    model_names = set(model_rules.keys())

    for name, data in model_rules.items():
        assert isinstance(name, str) and name.strip()
        assert isinstance(data, dict)

        assert data.get("category"), f"{name}: missing category"
        assert data.get("fabric_type"), f"{name}: missing fabric_type"
        assert data.get("identify_by"), f"{name}: missing identify_by"

        markers = data.get("visual_markers", [])
        assert isinstance(markers, list), f"{name}: visual_markers must be a list"
        assert len(markers) > 0, f"{name}: empty visual_markers"

        # No duplicated markers (case-insensitive)
        normalized = [str(m).strip().lower() for m in markers if str(m).strip()]
        assert len(normalized) == len(set(normalized)), f"{name}: duplicated visual_markers"

        confused = data.get("confused_with") or []
        assert isinstance(confused, list), f"{name}: confused_with must be a list"

        for other in confused:
            assert other in model_names, f"{name}: confused_with references unknown model: {other}"
            assert other != name, f"{name}: confused_with references itself"

    # Decision tree should exist and mention at least one known model
    decision_tree = rules.get("DECISION_TREE", "")
    assert isinstance(decision_tree, str)
    assert decision_tree.strip(), "DECISION_TREE is empty"

    assert any(m in decision_tree for m in model_names), (
        "DECISION_TREE does not mention any known model"
    )
