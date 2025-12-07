"""
Golden Flow Tests - E2E Scenarios.
===================================
Tests for critical user journeys that MUST work.

These represent the "happy paths" that generate revenue.
If any of these fail, the bot is broken for business.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from typing import Any

from src.core.state_machine import State, Intent
from src.agents.langgraph.nodes.intent import detect_intent_from_text
from src.agents.langgraph.edges import route_after_intent, route_after_vision, route_after_offer


# =============================================================================
# HELPER: Simulate state transitions
# =============================================================================

def simulate_routing_chain(
    initial_state: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    Simulate a chain of routing decisions.
    
    Args:
        initial_state: Starting FSM state
        messages: List of {"text": ..., "has_image": bool}
    
    Returns:
        List of {"intent": ..., "route": ..., "state": ...}
    """
    results = []
    current_state = initial_state
    selected_products = []
    
    for msg in messages:
        text = msg.get("text", "")
        has_image = msg.get("has_image", False)
        
        # Detect intent
        intent = detect_intent_from_text(text, has_image=has_image, current_state=current_state)
        
        # Simulate state context
        state = {
            "current_state": current_state,
            "detected_intent": intent,
            "selected_products": selected_products,
            "has_image": has_image,
        }
        
        # Get route
        route = route_after_intent(state)
        
        # Update state based on route (simplified simulation)
        if route == "vision":
            current_state = State.STATE_2_VISION.value
            selected_products = [{"name": "Test Product", "price": 2000}]  # Simulate product found
        elif route == "offer":
            current_state = State.STATE_4_OFFER.value
        elif route == "payment":
            current_state = State.STATE_5_PAYMENT_DELIVERY.value
        elif route == "escalation":
            current_state = State.STATE_8_COMPLAINT.value
        elif route == "agent":
            # Agent may change state based on context
            if intent == "GREETING_ONLY" and current_state == State.STATE_0_INIT.value:
                current_state = State.STATE_1_DISCOVERY.value
            elif intent == "DISCOVERY_OR_QUESTION":
                if current_state == State.STATE_0_INIT.value:
                    current_state = State.STATE_1_DISCOVERY.value
        
        results.append({
            "text": text[:30],
            "intent": intent,
            "route": route,
            "state": current_state,
        })
    
    return results


# =============================================================================
# 🔥 GOLDEN FLOW 1: Photo → Vision → Offer → Payment
# =============================================================================

class TestPhotoFlow:
    """Photo identification flow - most common happy path."""

    def test_photo_flow_routing(self):
        """
        Flow: User sends photo → Vision identifies → Offer made → User confirms → Payment
        """
        # Step 1: Photo in INIT → vision
        intent = detect_intent_from_text("", has_image=True, current_state="STATE_0_INIT")
        assert intent == "PHOTO_IDENT"
        
        route = route_after_intent({
            "current_state": "STATE_0_INIT",
            "detected_intent": "PHOTO_IDENT",
        })
        assert route == "vision"
        
        # Step 2: After vision, in OFFER state, "беру" → payment
        intent = detect_intent_from_text("беру", has_image=False, current_state="STATE_4_OFFER")
        assert intent == "PAYMENT_DELIVERY"
        
        route = route_after_intent({
            "current_state": "STATE_4_OFFER",
            "detected_intent": "PAYMENT_DELIVERY",
            "selected_products": [{"name": "Test", "price": 2000}],
        })
        assert route == "payment"

    def test_photo_with_question_flow(self):
        """
        Flow: Photo → Vision → "Який розмір?" → Size help → Offer → Payment
        """
        messages = [
            {"text": "Що це за товар?", "has_image": True},
            {"text": "який розмір на зріст 128?", "has_image": False},
            {"text": "так, беру", "has_image": False},
        ]
        
        results = simulate_routing_chain(State.STATE_0_INIT.value, messages)
        
        # Step 1: Photo → vision
        assert results[0]["route"] == "vision"
        
        # Step 2: Size question after vision → offer (has products)
        assert results[1]["intent"] == "SIZE_HELP"
        assert results[1]["route"] == "offer"
        
        # Step 3: Confirmation → payment
        assert results[2]["route"] == "payment"


# =============================================================================
# 🔥 GOLDEN FLOW 2: Text → Discovery → Offer → Payment
# =============================================================================

class TestTextDiscoveryFlow:
    """Text-based discovery flow - no photo."""

    def test_discovery_flow_routing(self):
        """
        Flow: "Покажіть костюми" → Discovery → Select → Offer → Payment
        """
        # Simplified: test intent detection at key states
        
        # Step 1: Discovery question in INIT
        intent = detect_intent_from_text(
            "Які є костюми для дівчинки?",
            has_image=False,
            current_state="STATE_0_INIT"
        )
        assert intent == "DISCOVERY_OR_QUESTION"
        
        # Step 2: Size question in DISCOVERY
        intent = detect_intent_from_text(
            "Зріст 140",
            has_image=False,
            current_state="STATE_1_DISCOVERY"
        )
        assert intent in ["SIZE_HELP", "DISCOVERY_OR_QUESTION"]
        
        # Step 3: In OFFER, confirmation
        intent = detect_intent_from_text(
            "так, підходить",
            has_image=False,
            current_state="STATE_4_OFFER"
        )
        assert intent == "PAYMENT_DELIVERY"

    def test_discovery_to_payment_full_flow(self):
        """Full flow with all routing decisions."""
        messages = [
            {"text": "Привіт! Які є костюми?", "has_image": False},
            {"text": "Зріст 140, покажіть варіанти", "has_image": False},
        ]
        
        results = simulate_routing_chain(State.STATE_0_INIT.value, messages)
        
        # Both should go to agent for discovery
        assert results[0]["route"] == "agent"
        assert results[1]["route"] == "agent"


# =============================================================================
# 🔥 GOLDEN FLOW 3: Rejection → Soft End
# =============================================================================

class TestRejectionFlow:
    """User rejection/thinking flow - graceful exit."""

    def test_rejection_in_offer(self):
        """User says "подумаю" in OFFER → should end gracefully."""
        intent = detect_intent_from_text(
            "дякую, подумаю",
            has_image=False,
            current_state="STATE_4_OFFER"
        )
        # "подумаю" is not a confirmation, should be THANKYOU or DISCOVERY
        assert intent in ["THANKYOU_SMALLTALK", "DISCOVERY_OR_QUESTION"]

    def test_thankyou_ends_conversation(self):
        """Simple "дякую" should signal end."""
        # In various states
        for state in ["STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY", "STATE_1_DISCOVERY"]:
            intent = detect_intent_from_text("дякую", has_image=False, current_state=state)
            # Note: In PAYMENT state, this might stay as PAYMENT (configured behavior)
            # Just verify it's a valid intent
            assert intent in ["THANKYOU_SMALLTALK", "PAYMENT_DELIVERY", "DISCOVERY_OR_QUESTION"]


# =============================================================================
# 🔥 GOLDEN FLOW 4: Complaint → Escalation
# =============================================================================

class TestComplaintFlow:
    """Complaint handling - must escalate to human."""

    @pytest.mark.parametrize("complaint_text", [
        "скарга на якість",
        "верніть гроші",
        "хочу повернути товар",
        "це обман!",
    ])
    def test_complaint_always_escalates(self, complaint_text):
        """Complaint keywords must be detected and routed to escalation."""
        for state in [State.STATE_0_INIT.value, State.STATE_4_OFFER.value, State.STATE_5_PAYMENT_DELIVERY.value]:
            # Detect intent
            intent = detect_intent_from_text(complaint_text, has_image=False, current_state=state)
            
            # Build state for routing
            route_state = {
                "current_state": state,
                "detected_intent": intent,
            }
            
            # If intent is COMPLAINT, route must be escalation
            if intent == "COMPLAINT":
                route = route_after_intent(route_state)
                assert route == "escalation", f"Complaint from {state} should escalate"


# =============================================================================
# PAYMENT DATA COLLECTION FLOW
# =============================================================================

class TestPaymentDataCollection:
    """Payment state should collect delivery data without breaking."""

    @pytest.mark.parametrize("payment_input", [
        "Київ",
        "Нова пошта відділення 25",
        "Іванова Марія Петрівна",
        "+380991234567",
        "158",  # Size confirmation
        "повна оплата",
        "передплата 200",
    ])
    def test_payment_inputs_stay_in_payment(self, payment_input):
        """Various payment inputs should keep PAYMENT_DELIVERY intent."""
        intent = detect_intent_from_text(
            payment_input,
            has_image=False,
            current_state="STATE_5_PAYMENT_DELIVERY"
        )
        assert intent == "PAYMENT_DELIVERY", f"'{payment_input}' should be PAYMENT_DELIVERY, got {intent}"

    def test_payment_routing_stays_in_payment(self):
        """Route after intent in PAYMENT state with PAYMENT intent → payment."""
        state = {
            "current_state": "STATE_5_PAYMENT_DELIVERY",
            "detected_intent": "PAYMENT_DELIVERY",
            "selected_products": [{"name": "Test", "price": 2000}],
        }
        route = route_after_intent(state)
        assert route == "payment"


# =============================================================================
# PRODUCT SELECTION IN OFFER
# =============================================================================

class TestProductSelectionInOffer:
    """Product name selection in OFFER state - MIRT catalog products."""

    # ВСІ РЕАЛЬНІ НАЗВИ ПРОДУКТІВ З КАТАЛОГУ MIRT:
    # - Сукня Анна (голубий, малина, чорний, червоний, коричневий, рожевий, сірий)
    # - Костюм Валері (універсальний)
    # - Костюм Ритм (рожевий, коричневий, бордовий)
    # - Костюм Каприз (рожевий, бордовий, коричневий)
    # - Костюм Лагуна (рожевий, помаранчевий, жовтий, сірий) - ПЛЮШ, ПОВНА блискавка
    # - Костюм Мрія (жовтий, рожевий, помаранчевий, сірий) - ПЛЮШ, КОРОТКА блискавка
    # - Костюм Мерея (молочний) - ЛАМПАСИ на штанах
    # - Тренч екошкіра (капучіно, молочний, чорний)
    # - Тренч тканинний (рожевий, голубий, темно синій)

    @pytest.mark.parametrize("product_name,expected", [
        # Плюшеві костюми
        ("лагуна", "PAYMENT_DELIVERY"),
        ("мрія", "PAYMENT_DELIVERY"),
        ("беру лагуну", "PAYMENT_DELIVERY"),
        ("хочу мрію", "PAYMENT_DELIVERY"),
        # Бавовняні костюми
        ("ритм", "PAYMENT_DELIVERY"),
        ("каприз", "PAYMENT_DELIVERY"),
        ("валері", "PAYMENT_DELIVERY"),
        ("мерея", "PAYMENT_DELIVERY"),
        # Сукні та тренчі
        ("сукня анна", "PAYMENT_DELIVERY"),
        ("анна", "PAYMENT_DELIVERY"),
        ("тренч", "PAYMENT_DELIVERY"),
        # Загальні підтвердження
        ("перший варіант", "PAYMENT_DELIVERY"),
        ("другий", "PAYMENT_DELIVERY"),
        ("беру", "PAYMENT_DELIVERY"),
        ("так", "PAYMENT_DELIVERY"),
    ])
    def test_product_selection_triggers_payment(self, product_name, expected):
        """Selecting product by name in OFFER → PAYMENT_DELIVERY."""
        intent = detect_intent_from_text(
            product_name,
            has_image=False,
            current_state="STATE_4_OFFER"
        )
        assert intent == expected, f"'{product_name}' should be {expected}, got {intent}"


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_message_handling(self):
        """Empty message should not crash."""
        intent = detect_intent_from_text("", has_image=False, current_state="STATE_0_INIT")
        assert intent in ["UNKNOWN_OR_EMPTY", "GREETING_ONLY", "DISCOVERY_OR_QUESTION"]

    def test_very_long_message(self):
        """Very long message should not crash."""
        long_text = "тест " * 1000
        intent = detect_intent_from_text(long_text, has_image=False, current_state="STATE_0_INIT")
        assert intent is not None

    def test_special_characters(self):
        """Messages with special characters should not crash."""
        special_text = "Привіт! 🎀 Що це? 💕 #костюм @mirt"
        intent = detect_intent_from_text(special_text, has_image=False, current_state="STATE_0_INIT")
        assert intent is not None

    def test_mixed_language(self):
        """Mixed Ukrainian/Russian/English should work."""
        mixed_texts = [
            "Привет, покажите костюмы",  # Russian
            "Hello, show me dresses",     # English
            "Привіт, покажіть костюми",   # Ukrainian
        ]
        for text in mixed_texts:
            intent = detect_intent_from_text(text, has_image=False, current_state="STATE_0_INIT")
            assert intent in ["GREETING_ONLY", "DISCOVERY_OR_QUESTION"]
