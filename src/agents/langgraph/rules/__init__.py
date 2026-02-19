"""
Rules Module - Single Source of Truth (SSOT) for Detection Rules.
===============================================================
Централізовані правила для детекції intent, transitions, та інших бізнес-логік.

Це SSOT для всіх keywords, patterns, та детекторів, які раніше були розкидані
по різних вузлах і створювали конфлікти/регресії.

Модулі:
- payment_proof.py: Детекція payment proof (скрін, квитанція, оплата)
- product_addition.py: Детекція наміру додати товар до замовлення
- cart_intent.py: Детекція intent додавання товару до кошика
"""

from .cart_intent import detect_add_to_cart
from .payment_proof import detect_payment_proof
from .product_addition import detect_product_addition_intent


__all__ = [
    "detect_payment_proof",
    "detect_product_addition_intent",
    "detect_add_to_cart",
]

