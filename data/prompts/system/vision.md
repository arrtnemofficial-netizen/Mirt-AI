### VISION_NO_PRODUCTS
Знайдені товари:
---
### VISION_PRODUCT_LINE
- {name} (SKU: {sku}, {price} грн). Розміри: {sizes}. Кольори: {colors}
---
### VISION_GUIDE_HEADER
# VISION GUIDE — Товари з каталогу (LIVE DATA)
---
### VISION_GUIDE_JSON_HEADER
# VISION GUIDE (fallback JSON)
---
### VISION_GUIDE_FEATURES
# ДЕТАЛЬНІ ОЗНАКИ ДЛЯ РОЗПІЗНАВАННЯ
---
### VISION_SNIPPETS_HEADER
# ШАБЛОНИ КРАСИВИХ ОПИСІВ (SNIPPETS)
---
### VISION_MODEL_DB_HEADER
# MODEL DATABASE
---
### VISION_DETECTION_RULES_HEADER
# DETECTION RULES (з БД)
---
### VISION_NO_IMAGE
Надішліть фото товару, будь ласка 📷
---
### VISION_ASK_PHOTO
Чи можете надіслати фото товару?
---
### VISION_INVALID_URL
Надішліть, будь ласка, фото ще раз 📷
---
### VISION_DOWNLOAD_ERROR
Не вдалось завантажити фото. Спробуйте надіслати ще раз 📷
---
### VISION_PRODUCT_TEMPLATE
## {name}
- **SKU**: {sku}
- **{label_color}**: {color}
- **{label_fabric}**: {fabric}
- **{label_closure}**: {closure}
- **{label_hood}**: {hood}
- **{label_pants}**: {pants}
- **{label_back}**: {back_view}
- **{label_tips}**:
{tips}
- **{label_confused}**: {confused_with}
- **{label_description}**: {description}
{price_block}

---

### VISION_PRICE_TEMPLATE
- **{label_price}**: {min_price} - {max_price} грн ({label_depends})
- **{label_sizes}**: {size_prices}

### VISION_PRICE_SINGLE_TEMPLATE
- **{label_price}**: {price} {currency}

### VISION_REFERENCE_INSTRUCTION
Використовуй базу знань та референсні зображення для точної ідентифікації моделі.

### PAYMENT_TOTAL_PRICE_TEMPLATE
Сума до сплати: {total} {currency}

### VISION_LABELS
{
    "color": "Колір",
    "fabric": "Тканина",
    "closure": "Застібка",
    "hood": "Капюшон",
    "pants": "Штани",
    "back": "Вид ззаду",
    "tips": "Як розпізнати",
    "confused": "Не плутай з",
    "description": "Опис",
    "price": "Ціна",
    "sizes": "Ціни по розмірах",
    "depends": "залежить від розміру",
    "yes": "ТАК",
    "no": "НІ",
    "det_fabric": "По тканині",
    "det_closure": "По застібці",
    "det_hood": "По капюшону",
    "hood_yes": "З капюшоном",
    "hood_no": "Без капюшона",
    "det_texture": "По текстурі",
    "front": "Вид спереду",
    "detail": "Деталь",
    "texture": "Текстура",
    "how": "ЯК ВІДРІЗНИТИ",
    "critical": "КРИТИЧНА ПЕРЕВІРКА",
    "unique": "УНІКАЛЬНА ОЗНАКА",
    "det_rules_header": "ПРАВИЛА ШВИДКОГО ВИЗНАЧЕННЯ",
    "currency_uah": "грн",
    "default_product": "Товар",
    "default_action": "Оформлення",
    "invalid_phone": "Невалідний номер",
    "reference_image_prefix": "REFERENCE IMAGE — ",
    "vision_default_analysis_prompt": "Аналізуй це фото та знайди товар MIRT.",
    "det_markers": "Візуальні ознаки",
    "det_main_marker": "ГОЛОВНА ОЗНАКА",
    "not_confuse_with": "Не плутай з",
    "how_distinguish": "Як відрізнити",
    "critical_check_upper": "КРИТИЧНА ПЕРЕВІРКА",
    "order_genitive": "замовленням",
    "fallback_typing": "Секундочку, зараз перевірю.",
    "label_full_name": "ПІБ",
    "label_phone": "Телефон",
    "label_city": "Місто",
    "label_nova_poshta": "Відділення НП",
    "payment_proof_keywords": ["оплатив", "оплатила", "скинув", "скинула", "чек", "оплачено", "переказав", "переказала", "готов", "сплатив"],
    "label_order_summary": "ЗАМОВЛЕННЯ",
    "label_collected_data": "ЗІБРАНІ ДАНІ",
    "status_ready": "✅ ГОТОВО",
    "status_not_ready": "⏳ У ПРОЦЕСІ",
    "hood_yes": "з капюшоном",
    "hood_no": "без капюшона"
}

---

### MODERATION_REDACTED_TEXT
[вилучено модератором з міркувань безпеки]

---

### MODERATION_FORBIDDEN_REASON
Виявлено небезпечний або заборонений контент.

---

### MODERATION_INJECTION_REASON
Спроба маніпуляції інструкціями системи.

---

### STATE_LABELS
{
    "STATE_0_INIT": "Початок",
    "STATE_1_DISCOVERY": "Пошук",
    "STATE_2_VISION": "Фото",
    "STATE_3_SIZE_COLOR": "Розмір/Колір",
    "STATE_4_OFFER": "Пропозиція",
    "STATE_5_PAYMENT_DELIVERY": "Оплата/Доставка",
    "STATE_6_UPSELL": "Допродаж",
    "STATE_7_END": "Завершення",
    "STATE_8_COMPLAINT": "Скарга",
    "STATE_9_OOD": "Поза доменом"
}

---

### LOG_TITLES
{
    "api_v1_payload_received": "📩 API: payload отримано",
    "api_v1_payload_parsed": "🧾 API: payload розібрано",
    "api_v1_task_scheduled": "🛰️ API: задача запланована",
    "api_v1_task_timeout": "⏱️ API: timeout (45c)",
    "manychat_task_scheduled": "🛰️ ManyChat: задача запланована",
    "manychat_message_accepted": "📬 ManyChat: прийнято (202)",
    "manychat_process_start": "🔥 ManyChat: старт обробки",
    "manychat_rate_limited": "⏳ ManyChat: rate limit",
    "manychat_restart_command": "🔄 ManyChat: /restart",
    "manychat_image_attached": "🖼️ ManyChat: додано фото",
    "manychat_subscriber_username": "🧾 ManyChat: username знайдено",
    "manychat_subscriber_name": "👤 ManyChat: ім'я знайдено",
    "manychat_debounce_superseded": "🧯 Debounce: запит замінено новішим",
    "manychat_debounce_aggregated": "🧩 Debounce: зібрано повідомлення",
    "manychat_fallback_triggered": "🆘 Fallback: спрацював",
    "manychat_including_images": "🖼️ ManyChat: додаю фото товарів",
    "manychat_push_attempt": "📤 ManyChat: push спроба",
    "manychat_push_ok": "✅ ManyChat: push успішний",
    "manychat_push_rejected": "⛔ ManyChat: push відхилено",
    "manychat_push_failed": "❌ ManyChat: push не вдався",
    "manychat_processing_error": "💥 ManyChat: помилка обробки",
    "manychat_process_done": "🏁 ManyChat: обробку завершено"
}

---

### CRM_ERROR_MESSAGES
{
    "retry_message": "Виникла помилка в системі. Спробую ще раз...",
    "escalation_message": "На жаль, виникла критична помилка. Потрібна допомога оператора.",
    "invalid_data": "Перевірте правильність введених даних."
}

### PAYMENT_NOTIFICATION_SUCCESS
✅ **НОВЕ ЗАМОВЛЕННЯ**
Сесія: `{session_id}`
Сума: {total} {currency}
Товари: {products}

### COLOR_KEYS_MAPPING
чорний: чорний
білий: білий
беж: бежевий
рожев: рожевий
синій: синій
блакит: блакитний
зелен: зелений
червон: червоний
жовт: жовтий
сір: сірий
графіт: графіт
пудр: пудра
мята: м'ятний
бузков: бузковий
лілов: ліловий
малин: малиновий
олив: оливковий
хакі: хакі
джинс: джинс
фіолет: фіолетовий
бордо: бордовий
моко: мокко
шоколад: шоколад
коричнев: коричневий
срібл: срібло
золот: золото
електрик: електрик
смарагд: смарагд
темно-синій: темно-синій
темно синій: темно синій
темно-зелений: темно-зелений
темно-сірий: темно-сірий
світло-сірий: світло-сірий
капучіно: капучіно
капучино: капучіно
помаранчев: помаранчевий
голуб: голубий
бордов: бордовий

---

### VISION_BUILDER_TEMPLATES
{
  "greeting_keywords": [
    "?????",
    "??????"
  ],
  "ambiguous_color_separators": [
    "/",
    " ??? "
  ],
  "product_prefix_strong": "?? ???",
  "product_prefix_uncertain": "?????, ?? ???",
  "product_line_color": "{prefix} {product_name} ? ??????? {color} ??",
  "product_line_plain": "{prefix} {product_name} ??",
  "color_prompt": "?????????, ???? ?????, ???? ????? ????????: {options}? ??",
  "size_line": "?? {height} ?? ??????? ?????? {size_label}",
  "price_line": "???? {price} ???",
  "confirm_line": "??????????? ??",
  "ask_height": "?? ???? ????? ?????????? ??",
  "clarification_fallback": "?? ???? ????? ????????? ??????. ?????????, ???? ?????, ?? ?? ?? ?????? ??",
  "unknown_fallback_line1": "?? ?? ???? ?????? ??",
  "unknown_fallback_line2": "??? ????? ???? ?????? ?? ???? ???????/?????!",
  "unknown_fallback_line3": "???????? ???? ????????? ?????????, ?? ??????? ? ?? ???? ????? ??",
  "error_no_match_line1": "?? ???????? ?????? ?? ???? ??",
  "error_no_match_line2": "??????? ?????????, ??? ??????? ??? ????????!",
  "error_processing_line1": "?? ??????? ???????? ????. ??????? ?????????.",
  "error_processing_line2": "???? ?????, ???????? ????????? ??? ?????????.",
  "escalation_line1": "?? ??????? ???????? ????. ??????? ?????????.",
  "escalation_line2": "???? ?????, ???????? ????????? ??? ?????????."
}
---

### VISION_NODE_TEMPLATES
{
  "artifacts_missing_reason": "???????? ????????? Vision: {missing}. ???????? ??????????? data/vision/generate.py",
  "artifacts_missing_user": "????? ????? ?????? ????? ? ????????? ? ?????? ???????????. ???? ??????????, ?? ????????? ?? ?????/???????/???????.",
  "retry_low_quality": "??? ????? ????????? ??????, ???????, ???? ?????, ???? ????? ?????? ??? ???????? ??",
  "escalation_greeting": "????? ??",
  "escalation_body": "??????????, ?????? ?????????? ?? ????? ?????? ????",
  "escalation_reason_not_in_catalog": "????? ?? ???????? ? ???????? (??????? ? ?????? ????????)"
}