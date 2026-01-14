from enum import Enum

class Route(str, Enum):
    """
    Unified Routing Constants.
    Eliminates magic strings in edges and routers.
    """
    AGENT = "agent"
    VISION = "vision"
    OFFER = "offer"
    PAYMENT = "payment"
    MODERATION = "moderation"
    ESCALATION = "escalation"
    UPSELL = "upsell"
    END = "end"
