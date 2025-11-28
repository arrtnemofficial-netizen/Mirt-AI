"""A/B Testing system for prompt variants.

Manages variant selection, tracking, and metrics collection.
"""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)

VARIANTS_FILE = Path(__file__).parent.parent.parent / "data" / "prompts" / "prompt_variants.yaml"


@dataclass
class VariantConfig:
    """Configuration for a prompt variant."""

    name: str
    weight: int
    enabled: bool
    rules: dict[str, Any]


@dataclass
class ABTestMetrics:
    """Metrics for A/B test variant."""

    variant_id: str
    total_sessions: int = 0
    total_messages: int = 0
    conversions: int = 0  # Замовлення
    escalations: int = 0
    json_errors: int = 0
    state_errors: int = 0
    total_response_time: float = 0.0

    @property
    def conversion_rate(self) -> float:
        return (self.conversions / self.total_sessions * 100) if self.total_sessions else 0

    @property
    def avg_messages_to_order(self) -> float:
        return (self.total_messages / self.conversions) if self.conversions else 0

    @property
    def escalation_rate(self) -> float:
        return (self.escalations / self.total_sessions * 100) if self.total_sessions else 0

    @property
    def avg_response_time(self) -> float:
        return (self.total_response_time / self.total_messages) if self.total_messages else 0


class ABTestingManager:
    """Manages A/B testing for prompt variants."""

    def __init__(self):
        self.variants: dict[str, VariantConfig] = {}
        self.metrics: dict[str, ABTestMetrics] = {}
        self.session_variants: dict[str, str] = {}  # session_id -> variant_id
        self._load_variants()

    def _load_variants(self) -> None:
        """Load variant configurations from YAML."""
        try:
            with open(VARIANTS_FILE, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            variants_config = config.get("VARIANTS", {})
            for variant_id, variant_data in variants_config.items():
                self.variants[variant_id] = VariantConfig(
                    name=variant_data["name"],
                    weight=variant_data["weight"],
                    enabled=variant_data["enabled"],
                    rules=variant_data.get("rules", {}),
                )
                self.metrics[variant_id] = ABTestMetrics(variant_id=variant_id)

            logger.info("Loaded %d A/B test variants", len(self.variants))
        except Exception as e:
            logger.error("Failed to load variants: %s", e)
            # Fallback to variant_a only
            self.variants = {
                "variant_a": VariantConfig(
                    name="Базовий",
                    weight=100,
                    enabled=True,
                    rules={},
                )
            }
            self.metrics["variant_a"] = ABTestMetrics(variant_id="variant_a")

    def get_variant_for_session(self, session_id: str) -> str:
        """Get variant ID for a session (consistent assignment)."""
        # Check if already assigned
        if session_id in self.session_variants:
            return self.session_variants[session_id]

        # Get enabled variants
        enabled = {k: v for k, v in self.variants.items() if v.enabled}
        if not enabled:
            return "variant_a"

        # Use hash of session_id for consistent assignment
        hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)

        # Weighted random selection based on hash
        total_weight = sum(v.weight for v in enabled.values())
        threshold = hash_val % total_weight

        cumulative = 0
        for variant_id, config in enabled.items():
            cumulative += config.weight
            if threshold < cumulative:
                self.session_variants[session_id] = variant_id
                logger.info("Assigned session %s to variant %s", session_id, variant_id)
                return variant_id

        # Fallback
        return list(enabled.keys())[0]

    def get_variant_rules(self, session_id: str) -> dict[str, Any]:
        """Get rules for session's variant."""
        variant_id = self.get_variant_for_session(session_id)
        return self.variants[variant_id].rules

    def track_session_start(self, session_id: str) -> None:
        """Track new session start."""
        variant_id = self.get_variant_for_session(session_id)
        self.metrics[variant_id].total_sessions += 1

    def track_message(self, session_id: str, response_time: float = 0.0) -> None:
        """Track message sent."""
        variant_id = self.get_variant_for_session(session_id)
        self.metrics[variant_id].total_messages += 1
        self.metrics[variant_id].total_response_time += response_time

    def track_conversion(self, session_id: str) -> None:
        """Track successful order (conversion)."""
        variant_id = self.get_variant_for_session(session_id)
        self.metrics[variant_id].conversions += 1
        logger.info("Conversion tracked for variant %s", variant_id)

    def track_escalation(self, session_id: str) -> None:
        """Track escalation to human."""
        variant_id = self.get_variant_for_session(session_id)
        self.metrics[variant_id].escalations += 1

    def track_json_error(self, session_id: str) -> None:
        """Track JSON parsing error."""
        variant_id = self.get_variant_for_session(session_id)
        self.metrics[variant_id].json_errors += 1

    def track_state_error(self, session_id: str) -> None:
        """Track state transition error."""
        variant_id = self.get_variant_for_session(session_id)
        self.metrics[variant_id].state_errors += 1

    def get_metrics_summary(self) -> dict[str, dict[str, Any]]:
        """Get summary of all metrics."""
        summary = {}
        for variant_id, metrics in self.metrics.items():
            summary[variant_id] = {
                "name": self.variants[variant_id].name,
                "total_sessions": metrics.total_sessions,
                "total_messages": metrics.total_messages,
                "conversions": metrics.conversions,
                "conversion_rate": f"{metrics.conversion_rate:.2f}%",
                "avg_messages_to_order": f"{metrics.avg_messages_to_order:.1f}",
                "escalation_rate": f"{metrics.escalation_rate:.2f}%",
                "avg_response_time": f"{metrics.avg_response_time:.2f}s",
            }
        return summary

    def get_winning_variant(self, min_sample_size: int = 100) -> str | None:
        """Determine winning variant based on conversion rate."""
        eligible = {k: v for k, v in self.metrics.items() if v.total_sessions >= min_sample_size}

        if len(eligible) < 2:
            return None  # Not enough data

        # Sort by conversion rate
        sorted_variants = sorted(eligible.items(), key=lambda x: x[1].conversion_rate, reverse=True)

        winner_id, winner_metrics = sorted_variants[0]
        logger.info(
            "Winning variant: %s (%.2f%% conversion, %d sessions)",
            winner_id,
            winner_metrics.conversion_rate,
            winner_metrics.total_sessions,
        )

        return winner_id


# Global instance
_ab_manager: ABTestingManager | None = None


def get_ab_manager() -> ABTestingManager:
    """Get or create global A/B testing manager."""
    global _ab_manager
    if _ab_manager is None:
        _ab_manager = ABTestingManager()
    return _ab_manager


def get_variant_for_session(session_id: str) -> str:
    """Convenience function to get variant for session."""
    return get_ab_manager().get_variant_for_session(session_id)


def get_variant_rules(session_id: str) -> dict[str, Any]:
    """Convenience function to get rules for session."""
    return get_ab_manager().get_variant_rules(session_id)
