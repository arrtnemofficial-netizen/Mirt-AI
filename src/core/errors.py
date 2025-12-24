"""Structured error system for service-level errors with actionable recommendations.

This module provides centralized error types for internal service validation
and health checks. Each error includes:
- Component name (e.g., "checkpointer", "llm_provider")
- Error code for automation (e.g., "CHECKPOINTER_TIMEOUT")
- Actionable recommendations (list of steps to resolve)
- Severity level (critical, warning, info)
- Context (masked sensitive data)

Usage:
    from src.core.errors import CheckpointerError
    
    raise CheckpointerError(
        error_code="CHECKPOINTER_TIMEOUT",
        message="Connection timeout after 10s",
        recommendations=[
            "1. Verify SUPABASE_URL is correct and accessible",
            "2. Check network connectivity",
            "3. Review connection pool settings"
        ],
        context={"timeout_seconds": 10.0, "pool_size": 10}
    )
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


def _mask_sensitive_data(value: str) -> str:
    """Mask sensitive data in strings (credentials, tokens, etc.).
    
    Examples:
        "postgresql://user:pass@host" -> "postgresql://user:***@host"
        "sk-abc123..." -> "sk-***"
    """
    if not isinstance(value, str):
        return str(value)
    
    # Mask database credentials: postgresql://user:pass@host
    value = re.sub(
        r"(postgresql|postgres|mysql|redis)://([^:]+):([^@]+)@",
        r"\1://\2:***@",
        value,
        flags=re.IGNORECASE
    )
    
    # Mask API keys: sk-abc123... -> sk-***
    value = re.sub(
        r"(sk-|pk-|Bearer\s+)([a-zA-Z0-9]{8,})",
        r"\1***",
        value,
        flags=re.IGNORECASE
    )
    
    # Mask tokens: token=abc123 -> token=***
    value = re.sub(
        r"(token|key|secret|password|api_key)\s*=\s*([^\s&]+)",
        r"\1=***",
        value,
        flags=re.IGNORECASE
    )
    
    return value


def _mask_dict_values(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively mask sensitive data in dictionary values."""
    masked = {}
    sensitive_keys = {
        "password", "passwd", "secret", "token", "key", "api_key",
        "connection_string", "database_url", "redis_url", "supabase_url"
    }
    
    for key, value in data.items():
        key_lower = key.lower()
        
        if any(sensitive in key_lower for sensitive in sensitive_keys):
            if isinstance(value, str):
                masked[key] = _mask_sensitive_data(value)
            else:
                masked[key] = "***"
        elif isinstance(value, dict):
            masked[key] = _mask_dict_values(value)
        elif isinstance(value, str):
            masked[key] = _mask_sensitive_data(value)
        else:
            masked[key] = value
    
    return masked


@dataclass
class ServiceError(Exception):
    """Base class for service errors with actionable recommendations.
    
    This is the foundation for all internal service validation errors.
    Each error provides structured information that can be:
    - Logged with full context
    - Displayed to operators with actionable steps
    - Used for automation (error_code)
    - Tracked in monitoring systems
    
    Attributes:
        component: Component name (e.g., "checkpointer", "llm_provider")
        error_code: Unique error code for automation (e.g., "CHECKPOINTER_TIMEOUT")
        message: Human-readable error message
        recommendations: List of actionable steps to resolve the issue
        severity: Error severity level (critical blocks startup, warning does not)
        context: Additional context (latency, pool status, etc.) - automatically masked
    """
    
    component: str
    error_code: str
    message: str
    recommendations: list[str]
    severity: Literal["critical", "warning", "info"] = "critical"
    context: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Validate error structure after initialization."""
        if not self.component:
            raise ValueError("ServiceError.component cannot be empty")
        if not self.error_code:
            raise ValueError("ServiceError.error_code cannot be empty")
        if not self.message:
            raise ValueError("ServiceError.message cannot be empty")
        if not self.recommendations:
            raise ValueError("ServiceError.recommendations cannot be empty")
        if self.severity not in ("critical", "warning", "info"):
            raise ValueError(f"ServiceError.severity must be 'critical', 'warning', or 'info', got '{self.severity}'")
    
    def __str__(self) -> str:
        """Human-readable error representation."""
        recs = "\n".join(f"  - {r}" for r in self.recommendations)
        return f"{self.component} [{self.error_code}]: {self.message}\nRecommendations:\n{recs}"
    
    def to_dict(self) -> dict[str, Any]:
        """Structured error representation for logging/monitoring.
        
        Automatically masks sensitive data in context.
        
        Returns:
            Dictionary with all error fields, suitable for JSON serialization
        """
        return {
            "component": self.component,
            "error_code": self.error_code,
            "message": self.message,
            "recommendations": self.recommendations,
            "severity": self.severity,
            "context": _mask_dict_values(self.context),
        }
    
    def is_critical(self) -> bool:
        """Check if error is critical (blocks startup)."""
        return self.severity == "critical"


@dataclass
class CheckpointerError(ServiceError):
    """Error related to checkpointer (PostgreSQL) operations.
    
    Used for database connection, query, and schema validation errors.
    """
    
    def __init__(
        self,
        error_code: str,
        message: str,
        recommendations: list[str],
        severity: Literal["critical", "warning", "info"] = "critical",
        context: dict[str, Any] | None = None,
    ):
        super().__init__(
            component="checkpointer",
            error_code=error_code,
            message=message,
            recommendations=recommendations,
            severity=severity,
            context=context or {},
        )


@dataclass
class LLMProviderError(ServiceError):
    """Error related to LLM provider operations.
    
    Used for API failures, quota issues, circuit breaker states.
    """
    
    def __init__(
        self,
        error_code: str,
        message: str,
        recommendations: list[str],
        severity: Literal["critical", "warning", "info"] = "critical",
        context: dict[str, Any] | None = None,
    ):
        super().__init__(
            component="llm_provider",
            error_code=error_code,
            message=message,
            recommendations=recommendations,
            severity=severity,
            context=context or {},
        )


@dataclass
class RedisError(ServiceError):
    """Error related to Redis operations.
    
    Used for connection, configuration, and availability errors.
    """
    
    def __init__(
        self,
        error_code: str,
        message: str,
        recommendations: list[str],
        severity: Literal["critical", "warning", "info"] = "critical",
        context: dict[str, Any] | None = None,
    ):
        super().__init__(
            component="redis",
            error_code=error_code,
            message=message,
            recommendations=recommendations,
            severity=severity,
            context=context or {},
        )


@dataclass
class ConfigurationError(ServiceError):
    """Error related to configuration validation.
    
    Used for invalid environment variables, format errors, cross-setting validation.
    """
    
    def __init__(
        self,
        error_code: str,
        message: str,
        recommendations: list[str],
        severity: Literal["critical", "warning", "info"] = "critical",
        context: dict[str, Any] | None = None,
    ):
        super().__init__(
            component="configuration",
            error_code=error_code,
            message=message,
            recommendations=recommendations,
            severity=severity,
            context=context or {},
        )


@dataclass
class LangGraphError(ServiceError):
    """Error related to LangGraph initialization and operations.
    
    Used for graph building, node execution, and state management errors.
    """
    
    def __init__(
        self,
        error_code: str,
        message: str,
        recommendations: list[str],
        severity: Literal["critical", "warning", "info"] = "critical",
        context: dict[str, Any] | None = None,
    ):
        super().__init__(
            component="langgraph",
            error_code=error_code,
            message=message,
            recommendations=recommendations,
            severity=severity,
            context=context or {},
        )


# Helper functions for generating common recommendations

def get_checkpointer_timeout_recommendations(timeout: float, pool_settings: dict[str, Any] | None = None) -> list[str]:
    """Generate recommendations for checkpointer timeout errors."""
    recs = [
        "1. Verify SUPABASE_URL is correct and accessible",
        "2. Check network connectivity: `curl <SUPABASE_URL>` (replace with your actual URL)",
        "3. Verify database credentials in SUPABASE_API_KEY",
        "4. Check if PgBouncer is enabled (requires prepare_threshold=None in connection pool)",
    ]
    
    if pool_settings:
        min_size = pool_settings.get("min_size", "unknown")
        max_size = pool_settings.get("max_size", "unknown")
        recs.append(f"5. Review connection pool settings: min_size={min_size}, max_size={max_size}")
    else:
        recs.append("5. Review connection pool settings: min_size=2, max_size=10")
    
    recs.append(f"6. Check if timeout ({timeout}s) is sufficient for your network latency")
    
    return recs


def get_llm_quota_recommendations(provider_name: str = "OpenAI") -> list[str]:
    """Generate recommendations for LLM quota exceeded errors."""
    return [
        f"1. Check {provider_name} quota status: https://platform.openai.com/account/usage",
        f"2. Verify billing information is up to date",
        f"3. Consider upgrading your {provider_name} plan if needed",
        "4. Check if circuit breaker is open (may need manual reset)",
        "5. Review usage patterns and consider rate limiting",
    ]


def get_redis_connection_recommendations(redis_url: str | None = None) -> list[str]:
    """Generate recommendations for Redis connection errors."""
    recs = [
        "1. Verify REDIS_URL is correct and accessible",
        "2. Check if Redis server is running: `redis-cli ping`",
        "3. Verify network connectivity to Redis server",
    ]
    
    if redis_url:
        # Mask the URL but show format hint
        masked = _mask_sensitive_data(redis_url)
        recs.append(f"4. Current REDIS_URL format: {masked}")
    
    recs.extend([
        "5. Check Redis server logs for errors",
        "6. Verify Redis authentication credentials if required",
    ])
    
    return recs


def get_configuration_validation_recommendations(setting_name: str, issue: str) -> list[str]:
    """Generate recommendations for configuration validation errors."""
    return [
        f"1. Verify {setting_name} is set correctly in environment variables",
        f"2. Check {setting_name} format: {issue}",
        "3. Review environment-specific configuration (production vs development)",
        "4. Ensure all required settings are present before startup",
    ]

