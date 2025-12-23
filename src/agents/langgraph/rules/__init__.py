"""
Rules Module - Single Source of Truth (SSOT) for Detection Rules.
===============================================================
Централізовані правила для детекції intent, transitions, та інших бізнес-логік.

Це SSOT для всіх keywords, patterns, та детекторів, які раніше були розкидані
по різних вузлах і створювали конфлікти/регресії.

Модулі:
- payment_proof.py: Детекція payment proof (скрін, квитанція, оплата)
- offer_transition.py: Детекція переходу з offer до payment (delivery request)
- cart_intent.py: Детекція intent додавання товару до кошика
"""

from .cart_intent import detect_add_to_cart
from .offer_transition import detect_delivery_request
from .payment_proof import detect_payment_proof

__all__ = [
    "detect_payment_proof",
    "detect_delivery_request",
    "detect_add_to_cart",
]

