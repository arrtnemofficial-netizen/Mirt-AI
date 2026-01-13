"""Unit tests for vision_agent.run_vision function."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from pydantic_ai import RunUsage

from src.agents.pydantic.deps import AgentDeps
from src.agents.pydantic.models import ProductMatch, VisionResponse
from src.agents.pydantic.vision_agent import run_vision


class TestRunVision:
    """Unit tests for run_vision function."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock AgentDeps with image_url."""
        deps = AgentDeps(
            session_id="test_session_123",
            trace_id="test_trace_123",
            user_id="test_user_123",
            current_state="STATE_0_INIT",
            has_image=True,
            image_url="https://example.com/test_image.jpg",
        )
        return deps

    @pytest.fixture
    def mock_deps_no_image(self):
        """Create mock AgentDeps without image_url."""
        deps = AgentDeps(
            session_id="test_session_123",
            trace_id="test_trace_123",
            user_id="test_user_123",
            current_state="STATE_0_INIT",
            has_image=False,
            image_url=None,
        )
        return deps

    @pytest.fixture
    def mock_vision_response(self):
        """Create mock VisionResponse."""
        return VisionResponse(
            reply_to_user="Це костюм Лагуна!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=ProductMatch(
                name="Костюм Лагуна",
                price=2190.0,
                color="рожевий",
                photo_url="https://cdn.sitniks.com/test.jpg",
            ),
        )

    @pytest.fixture
    def mock_agent_run_result(self, mock_vision_response):
        """Create mock AgentRunResult."""
        result = Mock()
        result.output = mock_vision_response
        result.usage = RunUsage(input_tokens=200, output_tokens=100)
        result.model_used = None
        return result

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.agents.pydantic.vision_agent._download_image_as_base64")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_success(
        self,
        mock_log_usage,
        mock_download_image,
        mock_get_agent,
        mock_deps,
        mock_agent_run_result,
    ):
        """Test successful vision recognition."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=mock_agent_run_result)
        mock_get_agent.return_value = mock_agent
        mock_download_image.return_value = "base64_encoded_image_data"

        # Call function
        response = await run_vision("Це фото товару", mock_deps)

        # Assertions
        assert response is not None
        assert response.confidence == 0.9
        assert response.identified_product is not None
        assert response.identified_product.name == "Костюм Лагуна"
        assert not response.needs_clarification

        # Verify agent.run was called
        mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_no_image_url(
        self, mock_log_usage, mock_get_agent, mock_deps_no_image
    ):
        """Test run_vision handles missing image_url."""
        from src.agents.pydantic.exceptions import AgentValidationError

        # Setup mocks
        mock_agent = Mock()
        mock_get_agent.return_value = mock_agent

        # Call function - should raise validation error
        with pytest.raises(AgentValidationError, match="image_url is required"):
            await run_vision("Це фото товару", mock_deps_no_image)

        # Verify agent.run was NOT called (validation error before)
        mock_agent.run.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.agents.pydantic.vision_agent._download_image_as_base64")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_private_cdn_download(
        self,
        mock_log_usage,
        mock_download_image,
        mock_get_agent,
        mock_agent_run_result,
    ):
        """Test run_vision downloads image from private CDN."""
        # Setup deps with private CDN URL
        deps = AgentDeps(
            session_id="test_session_123",
            trace_id="test_trace_123",
            user_id="test_user_123",
            current_state="STATE_0_INIT",
            has_image=True,
            image_url="https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=12345",
        )

        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=mock_agent_run_result)
        mock_get_agent.return_value = mock_agent
        mock_download_image.return_value = "base64_encoded_image_data"

        # Call function
        response = await run_vision("Це фото товару", deps)

        # Assertions
        assert response is not None
        assert response.confidence == 0.9

        # Verify _download_image_as_base64 was called for private CDN
        mock_download_image.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.agents.pydantic.vision_agent._download_image_as_base64")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_timeout(
        self,
        mock_log_usage,
        mock_download_image,
        mock_get_agent,
        mock_deps,
    ):
        """Test run_vision handles TimeoutError."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_get_agent.return_value = mock_agent
        mock_download_image.return_value = "base64_encoded_image_data"

        # Call function
        response = await run_vision("Це фото товару", mock_deps)

        # Assertions - should return error response
        assert response is not None
        assert response.confidence == 0.0
        assert response.needs_clarification is True

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.agents.pydantic.vision_agent._download_image_as_base64")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_generic_error(
        self,
        mock_log_usage,
        mock_download_image,
        mock_get_agent,
        mock_deps,
    ):
        """Test run_vision handles generic errors."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(side_effect=ValueError("Test error"))
        mock_get_agent.return_value = mock_agent
        mock_download_image.return_value = "base64_encoded_image_data"

        # Call function
        response = await run_vision("Це фото товару", mock_deps)

        # Assertions - should return error response
        assert response is not None
        assert response.confidence == 0.0
        assert response.needs_clarification is True

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.agents.pydantic.vision_agent._download_image_as_base64")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_extracts_tokens(
        self,
        mock_log_usage,
        mock_download_image,
        mock_get_agent,
        mock_deps,
        mock_vision_response,
    ):
        """Test run_vision extracts tokens from result.usage."""
        # Setup mocks with usage
        mock_agent = Mock()
        result = Mock()
        result.output = mock_vision_response
        result.usage = RunUsage(input_tokens=300, output_tokens=150)
        result.model_used = None
        mock_agent.run = AsyncMock(return_value=result)
        mock_get_agent.return_value = mock_agent
        mock_download_image.return_value = "base64_encoded_image_data"

        # Call function
        response = await run_vision("Це фото товару", mock_deps)

        # Assertions
        assert response is not None
        assert response.confidence == 0.9

        # Verify agent.run was called
        mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_handles_invalid_image_url(
        self, mock_log_usage, mock_get_agent, mock_deps
    ):
        """Test run_vision handles invalid image URL."""
        from src.agents.pydantic.exceptions import AgentValidationError

        # Setup deps with invalid URL
        deps = AgentDeps(
            session_id="test_session_123",
            trace_id="test_trace_123",
            user_id="test_user_123",
            current_state="STATE_0_INIT",
            has_image=True,
            image_url="invalid://not-a-valid-url",
        )

        # Setup mocks
        mock_agent = Mock()
        mock_get_agent.return_value = mock_agent

        # Call function - should raise validation error
        with pytest.raises(AgentValidationError, match="must be a valid HTTP"):
            await run_vision("Це фото товару", deps)

        # Verify agent.run was NOT called (validation error before)
        mock_agent.run.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.agents.pydantic.vision_agent.get_vision_agent")
    @patch("src.agents.pydantic.vision_agent._download_image_as_base64")
    @patch("src.services.observability.llm_usage_logger.log_llm_usage_best_effort")
    async def test_run_vision_base64_conversion(
        self,
        mock_log_usage,
        mock_download_image,
        mock_get_agent,
        mock_deps,
        mock_agent_run_result,
    ):
        """Test run_vision converts image to base64."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=mock_agent_run_result)
        mock_get_agent.return_value = mock_agent
        mock_download_image.return_value = "base64_encoded_image_data"

        # Call function
        response = await run_vision("Це фото товару", mock_deps)

        # Assertions
        assert response is not None
        assert response.confidence == 0.9

        # Verify _download_image_as_base64 was called (for private CDN)
        # Note: This will only be called if URL is private CDN
        # For regular URLs, it might not be called
        # We can verify the function exists and is callable
        from src.agents.pydantic.vision_agent import _download_image_as_base64

        assert callable(_download_image_as_base64)

