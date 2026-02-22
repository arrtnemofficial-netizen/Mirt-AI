from src.core.models import assert_core_model_literals_sync


def test_core_model_literals_sync_contract() -> None:
    """CI contract: Literal aliases in core models must stay synced with enums."""
    assert_core_model_literals_sync()
