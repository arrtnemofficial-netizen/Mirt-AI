# Налаштування ManyChat

## External Request

1) Створіть External Request у ManyChat.
2) URL: `https://<your-domain>/webhooks/manychat`
3) Headers:
   - `Content-Type: application/json`
   - `X-ManyChat-Token: <verify-token>`
4) Передайте `{{last_input_text}}` та `{{last_image_url}}` (якщо є).

## Важливо

- Увімкніть `MANYCHAT_PUSH_MODE=true`.
- Для Vision потрібен media proxy та allowlist CDN.

