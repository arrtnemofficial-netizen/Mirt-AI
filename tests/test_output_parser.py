"""Tests for robust output parser."""

import pytest

from src.core.models import AgentResponse
from src.core.output_parser import OutputParser, parse_llm_output


class TestOutputParser:
    """Test OutputParser with various malformed inputs."""

    def setup_method(self):
        self.parser = OutputParser(session_id="test123", current_state="STATE_1_DISCOVERY")

    def test_valid_json_string(self):
        """Test parsing valid JSON string."""
        raw = """{"event": "simple_answer", "messages": [{"type": "text", "content": "Hello"}], "products": [], "metadata": {"session_id": "test", "current_state": "STATE_1_DISCOVERY", "intent": "GREETING_ONLY"}}"""

        result = self.parser.parse(raw)

        assert isinstance(result, AgentResponse)
        assert result.event == "simple_answer"
        assert len(result.messages) == 1
        assert result.messages[0].content == "Hello"

    def test_json_in_markdown_block(self):
        """Test extracting JSON from markdown code block."""
        raw = """Here is my response:
        
```json
{"event": "simple_answer", "messages": [{"type": "text", "content": "Вітаю!"}], "products": [], "metadata": {"current_state": "STATE_0_INIT"}}
```

That's my answer."""

        result = self.parser.parse(raw)

        assert isinstance(result, AgentResponse)
        assert result.messages[0].content == "Вітаю!"

    def test_partial_json_extraction(self):
        """Test extracting JSON from mixed text."""
        raw = """I think the best answer is {"event": "simple_answer", "messages": [{"type": "text", "content": "Test"}], "products": [], "metadata": {}} because reasons."""

        result = self.parser.parse(raw)

        assert isinstance(result, AgentResponse)
        # Should fallback gracefully

    def test_plain_text_fallback(self):
        """Test fallback for plain text."""
        raw = "Вітаю! Я допоможу вам знайти одяг для дитини."

        result = self.parser.parse(raw)

        assert isinstance(result, AgentResponse)
        assert result.event == "simple_answer"
        assert "Вітаю" in result.messages[0].content

    def test_already_agent_response(self):
        """Test passing through AgentResponse object."""
        from src.core.models import Message, Metadata

        response = AgentResponse(
            event="greeting",
            messages=[Message(type="text", content="Hi")],
            products=[],
            metadata=Metadata(session_id="x", current_state="STATE_0_INIT"),
        )

        result = self.parser.parse(response)

        assert result is response

    def test_dict_input(self):
        """Test parsing dict input."""
        data = {
            "event": "product_showcase",
            "messages": [{"type": "text", "content": "Here are products"}],
            "products": [
                {
                    "id": 1,
                    "name": "Dress",
                    "price": 1000,
                    "photo_url": "https://example.com/img.jpg",
                }
            ],
            "metadata": {"current_state": "STATE_3_OFFER"},
        }

        result = self.parser.parse(data)

        assert result.event == "product_showcase"
        assert len(result.products) == 1

    def test_missing_event_defaults(self):
        """Test default event when missing."""
        data = {
            "messages": [{"type": "text", "content": "Test"}],
            "metadata": {},
        }

        result = self.parser.parse(data)

        assert result.event == "simple_answer"

    def test_missing_messages_extracts_text(self):
        """Test extracting text from various fields."""
        data = {
            "event": "simple_answer",
            "text": "This is the response",
            "metadata": {},
        }

        result = self.parser.parse(data)

        assert "This is the response" in result.messages[0].content

    def test_invalid_json_graceful_fallback(self):
        """Test graceful handling of invalid JSON."""
        raw = '{"event": "simple_answer", "messages": [broken json here'

        result = self.parser.parse(raw)

        assert isinstance(result, AgentResponse)
        # Should not crash, should have some content

    def test_empty_string(self):
        """Test handling empty string."""
        result = self.parser.parse("")

        assert isinstance(result, AgentResponse)
        assert len(result.messages) > 0
        assert "Вибачте" in result.messages[0].content or len(result.messages[0].content) > 0

    def test_none_handling(self):
        """Test handling None-like values."""
        result = self.parser.parse(None)

        assert isinstance(result, AgentResponse)

    def test_session_and_state_preservation(self):
        """Test that session_id and state are preserved."""
        parser = OutputParser(session_id="my-session", current_state="STATE_4_OFFER")

        result = parser.parse("Plain text response")

        assert result.metadata.session_id == "my-session"
        assert result.metadata.current_state == "STATE_4_OFFER"

    def test_product_validation(self):
        """Test product validation and filtering."""
        data = {
            "event": "product_showcase",
            "messages": [{"content": "Products"}],
            "products": [
                {"name": "Valid Product", "price": 500},
                {"invalid": "no name"},  # Should be filtered
                "not a dict",  # Should be filtered
            ],
            "metadata": {},
        }

        result = self.parser.parse(data)

        assert len(result.products) == 1
        assert result.products[0].name == "Valid Product"


class TestConvenienceFunction:
    """Test parse_llm_output convenience function."""

    def test_basic_usage(self):
        """Test basic convenience function usage."""
        result = parse_llm_output(
            "Hello world",
            session_id="sess1",
            current_state="STATE_2_REFINEMENT",
        )

        assert isinstance(result, AgentResponse)
        assert result.metadata.session_id == "sess1"


class TestEdgeCases:
    """Test edge cases and stress scenarios."""

    def test_very_long_text(self):
        """Test handling very long text."""
        long_text = "A" * 10000

        result = parse_llm_output(long_text)

        assert isinstance(result, AgentResponse)

    def test_unicode_content(self):
        """Test Unicode content handling."""
        raw = '{"event": "simple_answer", "messages": [{"type": "text", "content": "Привіт 🎀 Як справи? 👗"}], "products": [], "metadata": {}}'

        result = parse_llm_output(raw)

        assert "🎀" in result.messages[0].content
        assert "👗" in result.messages[0].content

    def test_nested_json_in_content(self):
        """Test JSON content that contains nested JSON."""
        raw = '{"event": "simple_answer", "messages": [{"type": "text", "content": "Data: {\\"key\\": \\"value\\"}"}], "products": [], "metadata": {}}'

        result = parse_llm_output(raw)

        assert isinstance(result, AgentResponse)

    def test_multiple_json_objects(self):
        """Test text with multiple JSON objects."""
        raw = '{"a": 1} some text {"event": "simple_answer", "messages": [{"content": "Real"}], "metadata": {}} more text'

        result = parse_llm_output(raw)

        assert isinstance(result, AgentResponse)
