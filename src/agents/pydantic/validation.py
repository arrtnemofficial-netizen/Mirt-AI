"""
Input validation for agent functions.

Validates deps, message, and image_url before agent execution.
"""

from src.agents.pydantic.deps import AgentDeps
from src.agents.pydantic.exceptions import AgentValidationError


def validate_agent_deps(deps: AgentDeps | None, agent_type: str) -> None:
    """
    Validate AgentDeps before agent execution.

    Args:
        deps: AgentDeps to validate
        agent_type: Type of agent (support, vision, payment)

    Raises:
        AgentValidationError: If deps is invalid
    """
    if not deps:
        raise AgentValidationError("deps cannot be None")

    if not deps.session_id:
        raise AgentValidationError("deps.session_id is required")

    if not deps.trace_id:
        raise AgentValidationError("deps.trace_id is required")

    if agent_type == "vision" and not deps.image_url:
        raise AgentValidationError("deps.image_url is required for vision agent")


def validate_message(message: str | None) -> str:
    """
    Validate and normalize message.

    Args:
        message: Message to validate

    Returns:
        Normalized message (stripped)

    Raises:
        AgentValidationError: If message is invalid
    """
    if message is None:
        raise AgentValidationError("message cannot be None")

    message = message.strip()

    if not message:
        raise AgentValidationError("message cannot be empty")

    if len(message) > 10000:  # Reasonable limit
        raise AgentValidationError(
            f"message too long: {len(message)} chars (max 10000)"
        )

    return message


def validate_image_url(image_url: str | None) -> str:
    """
    Validate image URL for vision agent.

    Args:
        image_url: Image URL to validate

    Returns:
        Normalized image URL (stripped)

    Raises:
        AgentValidationError: If image_url is invalid
    """
    if not image_url:
        raise AgentValidationError("image_url is required for vision agent")

    image_url = image_url.strip()

    if not image_url:
        raise AgentValidationError("image_url cannot be empty")

    if not (image_url.startswith("http://") or image_url.startswith("https://")):
        raise AgentValidationError(
            f"image_url must be a valid HTTP(S) URL: {image_url}"
        )

    if len(image_url) > 2048:  # Reasonable limit
        raise AgentValidationError(
            f"image_url too long: {len(image_url)} chars (max 2048)"
        )

    return image_url

