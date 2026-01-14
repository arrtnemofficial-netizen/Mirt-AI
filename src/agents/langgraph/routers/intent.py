"""
Intent Router.
==============
Routing logic after intent detection.
"""

7: from typing import Dict, Literal
8: import logging
9: from src.core.state_machine import State
10: from src.agents.langgraph.routers.base import safe_router, StateSchema
11: from src.agents.langgraph.routers.enums import Route
12: 
13: logger = logging.getLogger(__name__)
14: 
15: def get_intent_routes() -> Dict[str, str]:
16:     return {
17:         Route.VISION.value: "vision",
18:         Route.AGENT.value: "agent",
19:         Route.OFFER.value: "offer",
20:         Route.PAYMENT.value: "payment",
21:         Route.ESCALATION.value: "escalation",
22:         Route.END.value: "end",
23:     }
24: 
25: @safe_router
26: def route_after_intent(state: StateSchema) -> Literal["vision", "agent", "offer", "payment", "escalation", "end"]:
27:     """
28:     Decide where to go based on detected intent and current state.
29:     """
30:     intent = state.detected_intent
31:     current_state = state.state_enum
32:     has_image = state.has_image
33: 
34:     # 1. Escalation / Complaint
35:     if state.should_escalate or intent == "ESCALATION" or intent == "COMPLAINT":
36:         return Route.ESCALATION
37: 
38:     # 2. Greeting / Smalltalk -> Agent
39:     if intent in ("GREETING_ONLY", "THANKYOU_SMALLTALK"):
40:         return Route.AGENT
41: 
42:     # 3. Vision Flow (Image present)
43:     # Priority: If image is present, usually go to vision, UNLESS in payment flow
44:     if has_image:
45:         if current_state == State.STATE_5_PAYMENT_DELIVERY:
46:             # Check context: is it payment proof?
47:             # Intent logic should have handled this, but we double check
48:             if intent == "PAYMENT_DELIVERY":
49:                  return Route.PAYMENT
50: 
51:         # If intent is clearly photo ident, go to vision
52:         if intent == "PHOTO_IDENT":
53:             return Route.VISION
54: 
55:         # Fallback: if we are here with an image, and it's not payment, default to vision
56:         return Route.VISION
57: 
58:     # 4. Payment Flow
59:     if intent == "PAYMENT_DELIVERY":
60:         # SAFEGUARD: Only route to payment if we are already in payment state
61:         # OR if we have products selected.
62:         if current_state == State.STATE_5_PAYMENT_DELIVERY:
63:             return Route.PAYMENT
64: 
65:         if current_state == State.STATE_4_OFFER:
66:             return Route.PAYMENT
67: 
68:         # If user says "buy" but no products?
69:         if state.selected_products or state.offered_products:
70:             return Route.OFFER # Go to offer to confirm/finalize before payment?
71:             # Original logic:
72:             # if products -> offer
73:             # if no products -> agent
74: 
75:         return Route.AGENT
76: 
77:     # 5. Offer confirmation
78:     if current_state == State.STATE_4_OFFER and intent == "CONFIRMATION":
79:         return Route.PAYMENT
80: 
81:     # 6. Default: Agent
82:     return Route.AGENT
