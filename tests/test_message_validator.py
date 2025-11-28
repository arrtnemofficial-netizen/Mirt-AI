"""Tests for message validator."""

import pytest

from src.core.message_validator import MessageValidator, validate_incoming_message


class TestMessageValidator:
    """Test MessageValidator class."""

    def setup_method(self):
        self.validator = MessageValidator()

    def test_valid_text_message(self):
        """Test valid text message passes."""
        result = self.validator.validate_message("Привіт, шукаю плаття")

        assert result.is_valid
        assert result.exit_condition is None

    def test_empty_message_rejected(self):
        """Test empty message is rejected."""
        result = self.validator.validate_message("")

        assert not result.is_valid
        assert result.exit_condition is not None
        assert "Незрозуміле" in result.exit_condition

    def test_whitespace_only_rejected(self):
        """Test whitespace-only message is rejected."""
        result = self.validator.validate_message("   \n\t  ")

        assert not result.is_valid

    def test_none_message_rejected(self):
        """Test None message is rejected."""
        result = self.validator.validate_message(None)

        assert not result.is_valid

    def test_message_with_image_rejected(self):
        """Test message with image attachment is rejected."""
        attachments = [{"type": "image", "url": "https://example.com/img.jpg"}]
        result = self.validator.validate_message("Дивіться фото", attachments=attachments)

        assert not result.is_valid
        assert "Незрозуміле" in result.exit_condition

    def test_message_with_video_rejected(self):
        """Test message with video attachment is rejected."""
        attachments = [{"type": "video", "url": "https://example.com/vid.mp4"}]
        result = self.validator.validate_message("Відео", attachments=attachments)

        assert not result.is_valid

    def test_message_with_document_rejected(self):
        """Test message with document attachment is rejected."""
        attachments = [{"type": "document", "filename": "file.pdf"}]
        result = self.validator.validate_message("Документ", attachments=attachments)

        assert not result.is_valid

    def test_message_with_http_link_rejected(self):
        """Test message with http link is rejected."""
        result = self.validator.validate_message("Дивіться http://example.com")

        assert not result.is_valid
        assert "Незрозуміле" in result.exit_condition

    def test_message_with_https_link_rejected(self):
        """Test message with https link is rejected."""
        result = self.validator.validate_message("Сайт https://example.com")

        assert not result.is_valid

    def test_message_with_www_rejected(self):
        """Test message with www is rejected."""
        result = self.validator.validate_message("Перейдіть на www.example.com")

        assert not result.is_valid

    def test_message_with_ua_domain_rejected(self):
        """Test message with .ua domain is rejected."""
        result = self.validator.validate_message("Сайт example.ua")

        assert not result.is_valid

    def test_unreadable_special_chars_rejected(self):
        """Test message with too many special chars is rejected."""
        result = self.validator.validate_message("@#$%^&*()")

        assert not result.is_valid

    def test_short_emoji_only_rejected(self):
        """Test short emoji-only message is rejected."""
        result = self.validator.validate_message("👗")

        assert not result.is_valid

    def test_normal_emoji_with_text_accepted(self):
        """Test emoji with normal text is accepted."""
        result = self.validator.validate_message("Привіт 👋 шукаю плаття")

        assert result.is_valid

    def test_ukrainian_text_accepted(self):
        """Test Ukrainian text is accepted."""
        result = self.validator.validate_message("Доброго дня! Які у вас є костюми?")

        assert result.is_valid

    def test_numbers_accepted(self):
        """Test numbers in text are accepted."""
        result = self.validator.validate_message("Розмір 128, бюджет 2000 грн")

        assert result.is_valid

    def test_punctuation_accepted(self):
        """Test normal punctuation is accepted."""
        result = self.validator.validate_message("Привіт! Як справи? Все добре.")

        assert result.is_valid


class TestConvenienceFunction:
    """Test validate_incoming_message convenience function."""

    def test_basic_usage(self):
        """Test basic convenience function usage."""
        result = validate_incoming_message("Привіт")

        assert result.is_valid

    def test_with_attachments(self):
        """Test with attachments parameter."""
        attachments = [{"type": "photo"}]
        result = validate_incoming_message("Фото", attachments=attachments)

        assert not result.is_valid


class TestEdgeCases:
    """Test edge cases."""

    def test_very_long_valid_message(self):
        """Test very long but valid message."""
        long_text = "Привіт " * 100
        result = validate_incoming_message(long_text)

        assert result.is_valid

    def test_mixed_languages(self):
        """Test mixed Ukrainian and English."""
        result = validate_incoming_message("Привіт hello як справи?")

        assert result.is_valid

    def test_multiple_attachments(self):
        """Test multiple attachments."""
        attachments = [
            {"type": "image"},
            {"type": "video"},
        ]
        result = validate_incoming_message("Медіа", attachments=attachments)

        assert not result.is_valid

    def test_attachment_without_type(self):
        """Test attachment without type field."""
        attachments = [{"url": "https://example.com/file"}]
        result = validate_incoming_message("Файл", attachments=attachments)

        # Should pass as type is not in media_types
        assert result.is_valid

    def test_link_in_middle_of_text(self):
        """Test link in middle of text."""
        result = validate_incoming_message("Дивіться тут https://example.com дуже гарно")

        assert not result.is_valid
