"""
Tests for circuit breaker safeguards.

VERIFY_1: Тест що circuit breaker відкривається після N failures
VERIFY_2: Тест що circuit breaker закривається після recovery timeout
VERIFY_3: Лог причини відкриття
VERIFY_4: Тест інтеграції з fallback
"""

from __future__ import annotations

import logging
import time
from unittest.mock import patch

import pytest

from src.core.circuit_breaker import CircuitBreaker, CircuitState, get_circuit_breaker


def test_circuit_breaker_opens_after_failures():
    """VERIFY_1: Тест що circuit breaker відкривається після N failures."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=3, recovery_timeout=60.0)
    
    # Initially closed
    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True
    
    # Record 2 failures (not enough to open)
    breaker.record_failure(ValueError("Error 1"))
    breaker.record_failure(ValueError("Error 2"))
    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True
    
    # Record 3rd failure (should open)
    breaker.record_failure(ValueError("Error 3"))
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False


def test_circuit_breaker_recovery():
    """VERIFY_2: Тест що circuit breaker закривається після recovery timeout."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=2, recovery_timeout=0.1)  # 100ms
    
    # Open the circuit
    breaker.record_failure(ValueError("Error 1"))
    breaker.record_failure(ValueError("Error 2"))
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False
    
    # Wait for recovery timeout
    time.sleep(0.15)
    
    # Should transition to HALF_OPEN
    assert breaker.can_execute() is True  # This triggers HALF_OPEN transition
    assert breaker.state == CircuitState.HALF_OPEN
    
    # Record success in HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True


def test_circuit_breaker_detailed_logging(caplog):
    """VERIFY_3: Лог причини відкриття."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=2, recovery_timeout=60.0)
    
    with caplog.at_level(logging.WARNING):
        breaker.record_failure(TimeoutError("LLM timeout"))
        breaker.record_failure(ValueError("Invalid response"))
    
    # Check that logs contain detailed information
    log_messages = [record.message for record in caplog.records]
    circuit_logs = [msg for msg in log_messages if "[CIRCUIT:" in msg]
    
    assert len(circuit_logs) > 0, "Should log circuit breaker state changes"
    
    # Check that log contains required fields
    log_text = " ".join(circuit_logs)
    assert "error_type=" in log_text, "Should log error_type"
    assert "error_message=" in log_text, "Should log error_message"
    assert "failures" in log_text or "failure_count=" in log_text, "Should log failure count (either 'failures' or 'failure_count=')"
    assert "last_failure_time=" in log_text, "Should log last_failure_time"


def test_circuit_breaker_get_status():
    """Test that get_status returns all required metrics."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=3, recovery_timeout=60.0)
    
    status = breaker.get_status()
    
    # Should contain all required fields
    assert "state" in status
    assert "failure_count" in status
    assert "last_failure_time" in status
    assert "time_since_last_failure" in status
    assert "can_execute" in status
    assert "recovery_timeout" in status
    assert "failure_threshold" in status
    
    # Initial state
    assert status["state"] == "closed"
    assert status["failure_count"] == 0
    assert status["can_execute"] is True


def test_circuit_breaker_half_open_probe():
    """Test that HALF_OPEN state allows probe requests."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=1)
    
    # Open the circuit
    breaker.record_failure(ValueError("Error 1"))
    breaker.record_failure(ValueError("Error 2"))
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False
    
    # Wait for recovery
    time.sleep(0.15)
    
    # First call should be allowed (HALF_OPEN probe) - can_execute() transitions to HALF_OPEN
    can_exec = breaker.can_execute()
    assert can_exec is True, "First call in HALF_OPEN should be allowed"
    assert breaker.state == CircuitState.HALF_OPEN
    
    # Second call should be rejected (max_calls=1, already used)
    assert breaker.can_execute() is False, "Second call should be rejected (max_calls=1)"


def test_circuit_breaker_failure_in_half_open():
    """Test that failure in HALF_OPEN returns to OPEN."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=2, recovery_timeout=0.1)
    
    # Open the circuit
    breaker.record_failure(ValueError("Error 1"))
    breaker.record_failure(ValueError("Error 2"))
    
    # Wait for recovery
    time.sleep(0.15)
    breaker.can_execute()  # Transition to HALF_OPEN
    
    # Record failure in HALF_OPEN
    breaker.record_failure(ValueError("Probe failed"))
    
    # Should return to OPEN
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False


def test_circuit_breaker_success_in_half_open():
    """Test that success in HALF_OPEN closes the circuit."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=1)
    
    # Open the circuit
    breaker.record_failure(ValueError("Error 1"))
    breaker.record_failure(ValueError("Error 2"))
    
    # Wait for recovery
    time.sleep(0.15)
    breaker.can_execute()  # Transition to HALF_OPEN
    
    # Record success in HALF_OPEN
    breaker.record_success()
    
    # Should close the circuit
    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True
    assert breaker.failure_count == 0


def test_circuit_breaker_singleton():
    """Test that get_circuit_breaker returns singleton instances."""
    breaker1 = get_circuit_breaker("test_singleton")
    breaker2 = get_circuit_breaker("test_singleton")
    
    # Should be the same instance
    assert breaker1 is breaker2
    
    # Different names should return different instances
    breaker3 = get_circuit_breaker("test_different")
    assert breaker1 is not breaker3

