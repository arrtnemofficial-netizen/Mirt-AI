"""
Tests for payment requisites SSOT enforcement.

Ensures that:
1. Only canonical requisites exist in code (payment_config.py)
2. No conflicting IBAN/FOP/tax_id in state prompts
3. format_requisites_multiline returns canonical values
"""

import re
from pathlib import Path

import pytest

from src.conf.payment_config import BANK_REQUISITES, format_requisites_multiline


def test_requisites_ssot_canonical():
    """Test that payment_config.py contains canonical requisites."""
    assert BANK_REQUISITES.fop_name == "ФОП Кутна Наталія Романівна"
    assert BANK_REQUISITES.iban == "UA883220010000026000310028841"
    assert BANK_REQUISITES.tax_id == "3305504020"
    assert "ОПЛАТА ЗА ТОВАР" in BANK_REQUISITES.payment_purpose


def test_format_requisites_multiline_returns_canonical():
    """Test that format_requisites_multiline returns canonical requisites."""
    requisites_text = format_requisites_multiline()
    
    # Check that canonical values are present
    assert "ФОП Кутна Наталія Романівна" in requisites_text
    assert "UA883220010000026000310028841" in requisites_text
    assert "3305504020" in requisites_text
    assert "ОПЛАТА ЗА ТОВАР" in requisites_text
    
    # Check that canonical IBAN is present and no other full IBANs exist
    # IBAN format: UA + 2 digits + 14 digits = 29 characters total
    canonical_iban = "UA883220010000026000310028841"
    assert canonical_iban in requisites_text, "Canonical IBAN should be present in requisites"
    
    # Find all potential IBANs (UA + 2 digits + at least 10 more digits to avoid partial matches)
    iban_pattern = r"UA\d{2}\d{10,}"
    ibans_found = re.findall(iban_pattern, requisites_text)
    
    # Filter to only full IBANs (29 characters: UA + 27 digits)
    full_ibans = [iban for iban in ibans_found if len(iban) == 29]
    
    # Should only have canonical IBAN
    assert len(full_ibans) >= 1, "Should contain at least one full IBAN"
    assert all(iban == canonical_iban for iban in full_ibans), \
        f"Found non-canonical full IBANs: {full_ibans}"


def test_no_conflicting_requisites_in_state_prompts():
    """Test that state prompts don't contain conflicting IBAN/FOP/tax_id."""
    # Known conflicting values that should NOT exist
    conflicting_ibans = [
        "UA653220010000026003340139893",  # Old IBAN from STATE_5_PAYMENT_DELIVERY.md
        "UA913220010000026000360031220",  # Old IBAN from STATE_5_PAYMENT_DELIVERY_PAYMENT.md
    ]
    conflicting_fops = [
        "ФОП Кутний Михайло Михайлович",  # Old FOP from STATE_5_PAYMENT_DELIVERY.md
        "ФОП Кутний",  # Old FOP from STATE_5_PAYMENT_DELIVERY_PAYMENT.md
    ]
    conflicting_tax_ids = [
        "3278315599",  # Old tax ID from STATE_5_PAYMENT_DELIVERY.md
        "2572904585",  # Old tax ID from STATE_5_PAYMENT_DELIVERY_PAYMENT.md
    ]
    
    # Find all STATE_5_PAYMENT_DELIVERY*.md files
    base_dir = Path(__file__).parent.parent.parent / "data" / "prompts" / "states"
    state_files = list(base_dir.glob("STATE_5_PAYMENT_DELIVERY*.md"))
    
    assert len(state_files) > 0, "Should find at least one STATE_5_PAYMENT_DELIVERY*.md file"
    
    violations = []
    for file_path in state_files:
        content = file_path.read_text(encoding="utf-8")
        
        # Check for conflicting IBANs
        for iban in conflicting_ibans:
            if iban in content:
                violations.append(f"{file_path.name}: Found conflicting IBAN {iban}")
        
        # Check for conflicting FOPs (but allow canonical one)
        for fop in conflicting_fops:
            if fop in content and "ФОП Кутна Наталія Романівна" not in content:
                # Only flag if canonical FOP is not present (meaning old one is used)
                violations.append(f"{file_path.name}: Found conflicting FOP '{fop}'")
        
        # Check for conflicting tax IDs
        for tax_id in conflicting_tax_ids:
            if tax_id in content:
                violations.append(f"{file_path.name}: Found conflicting tax ID {tax_id}")
    
    assert len(violations) == 0, \
        f"Found conflicting requisites in state prompts:\n" + "\n".join(violations)


def test_state_prompts_reference_ssot():
    """Test that state prompts reference SSOT block instead of hardcoded requisites."""
    base_dir = Path(__file__).parent.parent.parent / "data" / "prompts" / "states"
    state_files = list(base_dir.glob("STATE_5_PAYMENT_DELIVERY*.md"))
    
    ssot_keywords = ["SSOT", "ssot", "SSOT блок", "SSOT-блок", "з SSOT"]
    
    for file_path in state_files:
        content = file_path.read_text(encoding="utf-8")
        
        # Check if file mentions SSOT (at least one reference)
        has_ssot_reference = any(keyword in content for keyword in ssot_keywords)
        
        # If file talks about requisites (but not just "оплатити" verb), it should reference SSOT
        # Check for actual requisites keywords, not just payment verbs
        has_requisites_keywords = (
            "реквізит" in content.lower() or 
            ("iban" in content.lower() and "оплатити" not in content.lower()) or
            "фоп" in content.lower() or
            "іпн" in content.lower() or
            "єдрпou" in content.lower()
        )
        
        if has_requisites_keywords:
            assert has_ssot_reference, \
                f"{file_path.name}: Mentions requisites but doesn't reference SSOT block"

