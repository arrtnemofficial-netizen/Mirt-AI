"""Single source of truth for vision escalation decision logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.agents.pydantic.models import VisionResponse


@dataclass(frozen=True)
class VisionEscalationDecision:
    should_escalate: bool
    reason: str
    confidence: float
    product_not_in_catalog: bool
    no_product_identified: bool


def evaluate_vision_escalation(
    response: "VisionResponse",
    catalog_row: dict[str, Any] | None,
    confidence_threshold: float = 0.75,
) -> VisionEscalationDecision:
    """Evaluate whether vision flow must escalate to a manager."""
    confidence = response.confidence or 0.0

    product_not_in_catalog = response.identified_product is not None and catalog_row is None
    no_product_identified = response.identified_product is None or (
        response.identified_product
        and (response.identified_product.name or "") in ("<not identified>", "<none>", "")
    )
    low_confidence = confidence < confidence_threshold
    very_low_confidence = confidence < 0.5

    should_escalate = product_not_in_catalog or (no_product_identified and low_confidence)
    if no_product_identified and very_low_confidence:
        should_escalate = True

    if product_not_in_catalog:
        reason = "product_not_in_catalog"
    elif no_product_identified:
        reason = "product_not_identified"
    else:
        reason = "low_confidence"

    return VisionEscalationDecision(
        should_escalate=should_escalate,
        reason=reason,
        confidence=confidence,
        product_not_in_catalog=product_not_in_catalog,
        no_product_identified=no_product_identified,
    )
