"""
Payment configuration (bank requisites).

Tests expect `BANK_REQUISITES` to exist and expose:
- fop_name
- iban
- tax_id
- payment_purpose

In production, you can override these via environment variables.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class _PaymentSettings(BaseSettings):
    PAYMENT_FOP_NAME: str = "ФОП Тестовий"
    PAYMENT_IBAN: str = "UA123456789012345678901234567"
    PAYMENT_TAX_ID: str = "1234567890"
    PAYMENT_PURPOSE: str = "Оплата за товар"


class BankRequisites(BaseModel):
    fop_name: str
    iban: str
    tax_id: str
    payment_purpose: str


_settings = _PaymentSettings()

BANK_REQUISITES = BankRequisites(
    fop_name=_settings.PAYMENT_FOP_NAME,
    iban=_settings.PAYMENT_IBAN,
    tax_id=_settings.PAYMENT_TAX_ID,
    payment_purpose=_settings.PAYMENT_PURPOSE,
)


