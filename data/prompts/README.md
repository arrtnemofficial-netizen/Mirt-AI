# 📚 Prompts Directory — SSOT Reference

## Canonical Values

| Item | SSOT Location | Value |
|------|---------------|-------|
| Bot Name | `system/main.md:4` | **Софія** |
| Brand | `system/main.md:4` | **MIRT_UA** |
| Prepay Amount | `payment_config.py:91` | **200 грн** |
| Bank Requisites | `payment_config.py:29` | ФОП Кутна Наталія Романівна |

---

## SSOT Injection (Runtime)

Payment requisites AND prepay amount are **injected at runtime**.

- **Requisites**: `shared/payment_prompts.py`
- **Prepay Amount**: `core/prompt_registry.py` replaces `{PAYMENT_PREPAY_AMOUNT}`

---

## Verification Commands

```bash
# Check bot name consistency
grep -r "Валерія" data/prompts/   # Should be 0
grep -r "Софія" data/prompts/     # Should be 7+

# Check prepay amount mentions
grep -r "200 грн" data/prompts/   # Document these
```
