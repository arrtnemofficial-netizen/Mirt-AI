import pytest
from src.services.cart import CartManager

def test_cart_manager_add_strict():
    manager = CartManager("test_session")

    current = [{"id": "1", "name": "Dress", "size": "M", "color": "Red"}]
    new_products = [{"id": "1", "name": "Dress", "size": "M", "color": "Red"}]

    updated, added = manager.add_products(current, new_products, strategy="strict")
    assert added == 0
    assert len(updated) == 1

def test_cart_manager_add_new():
    manager = CartManager("test_session")

    current = [{"id": "1", "name": "Dress", "size": "M", "color": "Red"}]
    new_products = [{"id": "2", "name": "Skirt", "size": "S", "color": "Blue"}]

    updated, added = manager.add_products(current, new_products, strategy="strict")
    assert added == 1
    assert len(updated) == 2

def test_cart_manager_soft_match():
    manager = CartManager("test_session")

    # Same name/size/color, different ID (or missing ID)
    current = [{"name": "Dress", "size": "M", "color": "Red"}]
    new_products = [{"id": "999", "name": "Dress", "size": "m", "color": "RED"}] # Case insensitive

    updated, added = manager.add_products(current, new_products, strategy="soft")
    assert added == 0
    assert len(updated) == 1
