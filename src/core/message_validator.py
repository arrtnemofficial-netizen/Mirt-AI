"""Message validator for checking empty messages, media, and links.

Implements strict rules from prompt:
- Empty messages = exit
- Messages with media = exit
- Messages with links = exit
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)

VARIANTS_FILE = Path(__file__).parent.parent.parent / "data" / "prompts" / "prompt_variants.yaml"


@dataclass
class ValidationResult:
    """Result of message validation."""

    is_valid: bool
    exit_condition: str | None = None
    reason: str | None = None


class MessageValidator:
    """Validates incoming messages before processing."""

    def __init__(self):
        self.media_types: list[str] = []
        self.link_patterns: list[str] = []
        self.exit_conditions: dict[str, str] = {}
        self._load_rules()

    def _load_rules(self) -> None:
        """Load validation rules from YAML."""
        try:
            with open(VARIANTS_FILE, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            media_rules = config.get("MEDIA_RULES", {})
            self.media_types = media_rules.get("media_types", [])
            self.link_patterns = media_rules.get("link_patterns", [])
            self.exit_conditions = media_rules.get("exit_conditions", {})

            logger.info("Loaded message validation rules")
        except Exception as e:
            logger.error("Failed to load validation rules: %s", e)
            # Fallback defaults
            self.media_types = ["image", "photo", "video", "audio", "document"]
            self.link_patterns = ["http://", "https://", "www."]
            self.exit_conditions = {
                "empty_message": "Незрозуміле повідомлення або незрозумілий формат повідомлення",
                "has_media": "Незрозуміле повідомлення або незрозумілий формат повідомлення",
                "has_link": "Незрозуміле повідомлення або незрозумілий формат повідомлення",
            }

    def validate_message(
        self,
        text: str | None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate incoming message.

        Args:
            text: Message text content
            attachments: List of attachments (media files)
            metadata: Additional message metadata

        Returns:
            ValidationResult with validation status
        """
        # Check 1: Empty message
        if not text or not text.strip():
            logger.warning("Empty message detected")
            return ValidationResult(
                is_valid=False,
                exit_condition=self.exit_conditions["empty_message"],
                reason="Порожнє повідомлення (можливо фото/відео)",
            )

        # Check 2: Has media attachments
        if attachments:
            has_media = any(att.get("type") in self.media_types for att in attachments)
            if has_media:
                logger.warning("Message with media detected")
                return ValidationResult(
                    is_valid=False,
                    exit_condition=self.exit_conditions["has_media"],
                    reason="Повідомлення містить медіа (фото/відео/файл)",
                )

        # Check 3: Has links in text
        if self._contains_link(text):
            logger.warning("Message with link detected")
            return ValidationResult(
                is_valid=False,
                exit_condition=self.exit_conditions["has_link"],
                reason="Повідомлення містить посилання",
            )

        # Check 4: Unreadable characters (optional)
        if self._is_unreadable(text):
            logger.warning("Unreadable message detected")
            return ValidationResult(
                is_valid=False,
                exit_condition=self.exit_conditions["empty_message"],
                reason="Незрозумілі символи або формат",
            )

        # All checks passed
        return ValidationResult(is_valid=True)

    def _contains_link(self, text: str) -> bool:
        """Check if text contains links."""
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in self.link_patterns)

    def _is_unreadable(self, text: str) -> bool:
        """Check if text is unreadable (too many special chars)."""
        # Remove whitespace
        text_clean = text.strip()

        # If very short and only special chars
        if len(text_clean) < 3:
            return True

        # Count alphanumeric vs special chars
        alnum_count = sum(c.isalnum() for c in text_clean)
        total_count = len(text_clean)

        # If less than 30% alphanumeric - probably unreadable
        if total_count > 0 and (alnum_count / total_count) < 0.3:
            return True

        return False


# Global instance
_validator: MessageValidator | None = None


def get_message_validator() -> MessageValidator:
    """Get or create global message validator."""
    global _validator
    if _validator is None:
        _validator = MessageValidator()
    return _validator


def validate_incoming_message(
    text: str | None,
    attachments: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ValidationResult:
    """Convenience function for message validation."""
    validator = get_message_validator()
    return validator.validate_message(text, attachments, metadata)
