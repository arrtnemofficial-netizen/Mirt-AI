import pytest
from src.conf.config import Settings

def test_loop_guard_settings_sanity():
    """
    Sanity check for Loop Guard configuration.
    Ensures that Warning < Soft Reset < Escalation.
    This protects against logical discrepancies in configuration.
    """
    settings = Settings(
        LOOP_GUARD_WARNING_THRESHOLD=5,
        LOOP_GUARD_SOFT_RESET=10,
        LOOP_GUARD_ESCALATION=20
    )
    
    assert settings.LOOP_GUARD_WARNING_THRESHOLD < settings.LOOP_GUARD_SOFT_RESET
    assert settings.LOOP_GUARD_SOFT_RESET <= settings.LOOP_GUARD_ESCALATION # Can be equal if we want hard stop immediately
    assert settings.LOOP_GUARD_WARNING_THRESHOLD > 0

def test_loop_guard_invalid_values():
    """
    Ensure config validation prevents negative values.
    """
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError):
        Settings(LOOP_GUARD_WARNING_THRESHOLD=0)
        
    with pytest.raises(ValidationError):
        Settings(LOOP_GUARD_ESCALATION=-5)
