"""Pre-flight configuration validation.

This module validates configuration format and consistency BEFORE attempting
any connections. This catches configuration errors early and provides
actionable recommendations.

Pre-flight checks:
- URL format validation (SUPABASE_URL, REDIS_URL)
- API key format hints (OpenAI keys start with 'sk-')
- Cross-setting validation (CELERY_ENABLED requires REDIS_URL)
- Environment-specific validation (production vs development)

These checks are FAST (no network calls) and run BEFORE service initialization.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from src.core.errors import (
    ConfigurationError,
    get_configuration_validation_recommendations,
)

logger = logging.getLogger(__name__)


def validate_url_format(url: str, setting_name: str) -> tuple[bool, str | None]:
    """Validate URL format without making network calls.
    
    Args:
        url: URL string to validate
        setting_name: Name of the setting (for error messages)
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url or not url.strip():
        return False, f"{setting_name} is empty"
    
    try:
        parsed = urlparse(url)
        
        # Check for required components
        if not parsed.scheme:
            return False, f"{setting_name} missing scheme (http://, https://, postgresql://, etc.)"
        
        # Validate scheme for known types
        valid_schemes = {
            "http", "https", "postgresql", "postgres", "redis", "rediss"
        }
        if parsed.scheme not in valid_schemes:
            return False, f"{setting_name} has invalid scheme '{parsed.scheme}'. Expected one of: {', '.join(valid_schemes)}"
        
        # For database URLs, check for host
        if parsed.scheme in ("postgresql", "postgres", "redis", "rediss"):
            if not parsed.hostname:
                return False, f"{setting_name} missing hostname"
        
        return True, None
        
    except Exception as e:
        return False, f"{setting_name} URL parsing error: {str(e)[:100]}"


def validate_api_key_format(api_key: str, setting_name: str, expected_prefix: str | None = None) -> tuple[bool, str | None]:
    """Validate API key format (prefix check, length).
    
    Args:
        api_key: API key string to validate
        setting_name: Name of the setting (for error messages)
        expected_prefix: Expected prefix (e.g., 'sk-' for OpenAI)
    
    Returns:
        Tuple of (is_valid, warning_message) - warnings, not errors, because
        custom APIs may have different formats
    """
    if not api_key or not api_key.strip():
        return False, f"{setting_name} is empty"
    
    # Check length (most API keys are at least 20 characters)
    if len(api_key) < 10:
        return False, f"{setting_name} seems too short (expected at least 10 characters)"
    
    # Check prefix if provided
    if expected_prefix and not api_key.startswith(expected_prefix):
        return True, f"{setting_name} doesn't start with expected prefix '{expected_prefix}' (may be valid for custom APIs)"
    
    return True, None


async def validate_configuration() -> dict[str, Any]:
    """Pre-flight configuration validation.
    
    Validates configuration format and consistency BEFORE any connections.
    Returns warnings for format issues, errors for critical inconsistencies.
    
    Returns:
        dict with validation results:
        {
            "all_valid": bool,
            "errors": list[dict],  # Critical issues (block startup)
            "warnings": list[dict],  # Format issues (don't block startup)
            "checks": dict[str, dict]  # Per-setting check results
        }
    """
    from src.conf.config import get_settings
    
    settings = get_settings()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: dict[str, dict[str, Any]] = {}
    
    # Determine environment
    import os
    env = os.getenv("ENVIRONMENT", "development").lower()
    is_production = env in ("production", "prod", "staging") or (
        settings.PUBLIC_BASE_URL != "http://localhost:8000"
    )
    
    # ==========================================================================
    # CRITICAL SETTINGS VALIDATION (Production)
    # ==========================================================================
    if is_production:
        # SUPABASE_URL format validation
        if settings.SUPABASE_URL:
            is_valid, error_msg = validate_url_format(settings.SUPABASE_URL, "SUPABASE_URL")
            checks["supabase_url"] = {"status": "ok" if is_valid else "warning", "message": error_msg}
            if not is_valid:
                warnings.append({
                    "setting": "SUPABASE_URL",
                    "issue": error_msg or "Invalid URL format",
                    "severity": "warning",
                })
        else:
            errors.append({
                "setting": "SUPABASE_URL",
                "issue": "Required in production but not set",
                "severity": "critical",
            })
            checks["supabase_url"] = {"status": "error", "message": "Not set"}
        
        # SUPABASE_API_KEY format validation
        if settings.SUPABASE_API_KEY.get_secret_value():
            # Supabase keys are typically long strings, no specific prefix
            is_valid, warning_msg = validate_api_key_format(
                settings.SUPABASE_API_KEY.get_secret_value(),
                "SUPABASE_API_KEY"
            )
            checks["supabase_api_key"] = {"status": "ok" if is_valid else "warning", "message": warning_msg}
            if warning_msg:
                warnings.append({
                    "setting": "SUPABASE_API_KEY",
                    "issue": warning_msg,
                    "severity": "warning",
                })
        else:
            errors.append({
                "setting": "SUPABASE_API_KEY",
                "issue": "Required in production but not set",
                "severity": "critical",
            })
            checks["supabase_api_key"] = {"status": "error", "message": "Not set"}
        
        # OPENAI_API_KEY format validation
        if settings.OPENAI_API_KEY.get_secret_value():
            is_valid, warning_msg = validate_api_key_format(
                settings.OPENAI_API_KEY.get_secret_value(),
                "OPENAI_API_KEY",
                expected_prefix="sk-"
            )
            checks["openai_api_key"] = {"status": "ok" if is_valid else "warning", "message": warning_msg}
            if warning_msg and "doesn't start" in warning_msg:
                warnings.append({
                    "setting": "OPENAI_API_KEY",
                    "issue": warning_msg,
                    "severity": "warning",
                })
        else:
            errors.append({
                "setting": "OPENAI_API_KEY",
                "issue": "Required in production but not set",
                "severity": "critical",
            })
            checks["openai_api_key"] = {"status": "error", "message": "Not set"}
    
    # ==========================================================================
    # CROSS-SETTING VALIDATION
    # ==========================================================================
    
    # CELERY_ENABLED requires REDIS_URL
    if settings.CELERY_ENABLED:
        if not settings.REDIS_URL or settings.REDIS_URL == "redis://localhost:6379/0":
            errors.append({
                "setting": "REDIS_URL",
                "issue": "CELERY_ENABLED=True requires REDIS_URL to be configured (not default)",
                "severity": "critical",
            })
            checks["redis_url"] = {"status": "error", "message": "Required but not configured"}
        else:
            # Validate Redis URL format
            is_valid, error_msg = validate_url_format(settings.REDIS_URL, "REDIS_URL")
            checks["redis_url"] = {"status": "ok" if is_valid else "warning", "message": error_msg}
            if not is_valid:
                errors.append({
                    "setting": "REDIS_URL",
                    "issue": error_msg or "Invalid URL format",
                    "severity": "critical",
                })
    
    # ==========================================================================
    # OPTIONAL SETTINGS VALIDATION (Warnings only)
    # ==========================================================================
    
    # REDIS_URL format (if set but not required)
    if settings.REDIS_URL and settings.REDIS_URL != "redis://localhost:6379/0":
        if not settings.CELERY_ENABLED:
            is_valid, error_msg = validate_url_format(settings.REDIS_URL, "REDIS_URL")
            if not is_valid:
                warnings.append({
                    "setting": "REDIS_URL",
                    "issue": error_msg or "Invalid URL format (not required, but may cause issues if used)",
                    "severity": "warning",
                })
    
    # MANYCHAT_API_KEY format (if set)
    if settings.MANYCHAT_API_KEY.get_secret_value():
        is_valid, warning_msg = validate_api_key_format(
            settings.MANYCHAT_API_KEY.get_secret_value(),
            "MANYCHAT_API_KEY"
        )
        checks["manychat_api_key"] = {"status": "ok" if is_valid else "warning", "message": warning_msg}
        if warning_msg:
            warnings.append({
                "setting": "MANYCHAT_API_KEY",
                "issue": warning_msg,
                "severity": "warning",
            })
    
    # PUBLIC_BASE_URL format (if not default)
    if settings.PUBLIC_BASE_URL and settings.PUBLIC_BASE_URL != "http://localhost:8000":
        is_valid, error_msg = validate_url_format(settings.PUBLIC_BASE_URL, "PUBLIC_BASE_URL")
        checks["public_base_url"] = {"status": "ok" if is_valid else "warning", "message": error_msg}
        if not is_valid:
            warnings.append({
                "setting": "PUBLIC_BASE_URL",
                "issue": error_msg or "Invalid URL format",
                "severity": "warning",
            })
    
    all_valid = len(errors) == 0
    
    return {
        "all_valid": all_valid,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "environment": "production" if is_production else "development",
    }


async def validate_and_raise_on_errors() -> None:
    """Validate configuration and raise ConfigurationError if critical errors found.
    
    This is the main entry point for pre-flight validation.
    Should be called BEFORE any service initialization.
    
    Raises:
        ConfigurationError: If critical configuration errors are found
    """
    result = await validate_configuration()
    
    # Log warnings (don't block startup)
    for warning in result["warnings"]:
        logger.warning(
            "[PREFLIGHT] Configuration warning: %s - %s",
            warning["setting"],
            warning["issue"]
        )
    
    # Raise errors for critical issues
    if not result["all_valid"]:
        error_messages = []
        recommendations = []
        
        for error in result["errors"]:
            setting = error["setting"]
            issue = error["issue"]
            error_messages.append(f"{setting}: {issue}")
            
            # Generate recommendations for this setting
            recs = get_configuration_validation_recommendations(setting, issue)
            recommendations.extend(recs)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique_recommendations.append(rec)
        
        raise ConfigurationError(
            error_code="CONFIGURATION_VALIDATION_FAILED",
            message=f"Pre-flight configuration validation failed: {', '.join(error_messages)}",
            recommendations=unique_recommendations,
            severity="critical",
            context={
                "environment": result["environment"],
                "errors": result["errors"],
                "warnings_count": len(result["warnings"]),
            }
        )

