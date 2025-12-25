"""Centralized payment configuration: requisites, prices, size mapping.

Single Source of Truth for:
- Bank requisites (FOP name, IBAN, tax ID)
- Text snippets used in prompts and agent overrides

All payment-related code should import from this module instead of
hardcoding requisites/IBAN/tax ID in multiple places.
"""

from __future__ import annotations

from dataclasses import dataclass


# =============================================================================
# BANK REQUISITES
# =============================================================================


@dataclass(frozen=True)
class BankRequisites:
    fop_name: str
    iban: str
    tax_id: str
    payment_purpose: str


BANK_REQUISITES = BankRequisites(
    fop_name="ФОП Кутна Наталія Романівна",
    iban="UA883220010000026000310028841",
    tax_id="3305504020",
    payment_purpose="ОПЛАТА ЗА ТОВАР і ваше ПІБ❣️",
)


def format_requisites_multiline() -> str:
    """
    Return human-friendly multiline requisites block for chat messages.
    
    Format matches the required template:
    - First bubble: FOP name, IBAN, tax ID, payment purpose
    - Second bubble: IBAN only (for easy copy)
    - Third bubble: Request for payment receipt
    """
    return (
        f"Отримувач: {BANK_REQUISITES.fop_name}\n"
        f"IBAN: {BANK_REQUISITES.iban}\n"
        f"ІПН/ЄДРПОУ: {BANK_REQUISITES.tax_id}\n"
        f"Призначення платежу\n"
        f"{BANK_REQUISITES.payment_purpose}"
    )


def format_requisites_with_receipt_request() -> list[str]:
    """
    Return requisites formatted as separate message bubbles for ManyChat/IG.
    
    Returns:
        List of message texts (one per bubble)
    """
    return [
        format_requisites_multiline(),
        BANK_REQUISITES.iban,
        "Надішліть, будь ласка, квитанцію після оплати, щоб ми одразу сформували замовлення для вас 🙂",
    ]


def format_requisites_short() -> str:
    """Short variant without purpose (for compact prompts)."""

    return f"{BANK_REQUISITES.fop_name}\nIBAN: {BANK_REQUISITES.iban}"


# =============================================================================
# PAYMENT AMOUNTS & PRICE TIERS
# =============================================================================

# Fixed prepayment amount used across prompts and agent logic
PAYMENT_PREPAY_AMOUNT: int = 200

# Fallback price (UAH) when product price is missing.
# Does NOT override catalog/DB prices; used only as last resort.
PAYMENT_DEFAULT_PRICE: int = 2180

# Size-based price tiers for костюми Лагуна, Мрія, Мерея used in prompts.
SUIT_PRICE_BY_SIZE: dict[str, int] = {
    "80-92": 1590,
    "98-104": 1790,
    "110-116": 1990,
    "122-128": 2190,
    "134-140": 2290,
    "146-152": 2390,
    "158-164": 2390,
}
