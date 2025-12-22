# AI Sphere (MIRT AI) — Архітектурний гайд, QA чек‑лист і правила контенту

Цей документ об’єднує:
1) Архітектурний гайд (SSOT, Registry, контракти, валідація)
2) Технічний чек‑лист якості / anti‑hallucination
3) Правила контенту (snippets / fallbacks / intents / system_messages)

Версія: 1.0
Статус: живий документ (оновлюється разом із кодом)

---

# 1) Архітектурний гайд

## 1.1. Принцип SSOT (Single Source of Truth)

SSOT — це правило №1 у проєкті. 
Будь‑який текст, правило чи дані, що впливають на відповідь користувачу, мають єдине джерело істини.

Що є SSOT у цьому проєкті:
- data/prompts/system/base_identity.md — ідентичність, формат, мова
- data/prompts/system/snippets.md — діалоги і шаблони менеджера
- data/prompts/system/fallbacks.md — помилки/таймаути/дефолти
- data/prompts/system/intents.md — патерни для intent detection
- data/prompts/system/system_messages.md — службові/бот‑повідомлення
- data/prompts/states/*.md — state‑промпти для FSM
- data/vision/generated/* — артефакти для vision
- data/vision/products_master.yaml — джерело даних по товарах

Правило: якщо текст живе у коді, він не є SSOT і не гарантує стабільність.


## 1.2. Registry як контракт між кодом і контентом

Registry — єдина точка доступу до промптів/контенту. 
Код не зберігає тексти, лише ключі для пошуку.

Основний доступ:
- registry.get("system.snippets")
- registry.get("system.fallbacks")
- registry.get("system.intents")
- registry.get("system.system_messages")
- registry.get("state.STATE_4_OFFER")

Ідея: контент може змінюватись без редеплою.


## 1.3. Контракти (Pydantic Output Contract)

Контракт — це гарантія структури. 
Навіть якщо LLM помиляється, вихід має бути валідним.

Приклади контрактів:
- SupportResponse (main agent)
- VisionResponse (vision agent)
- PaymentResponse (payment agent)
- OfferResponse (offer agent)

Умови:
- messages[] завжди non‑empty
- metadata має current_state, intent, escalation_level
- products тільки з CATALOG


## 1.4. Валідація як страховка

Валідація — це фільтр між LLM і користувачем.

Є кілька рівнів:
- Структурна перевірка (schema, поля)
- Валідація товарів (price, size, photo_url)
- Валідація бізнес‑логіки (state transition, intent)

Ціль: ловити помилки до того, як їх побачить клієнт.


## 1.5. Fail‑Fast і Escalation

Якщо критичні дані відсутні або система в нестабільному стані:
- швидкий вихід у fallback
- ескалація менеджеру

Приклад: відсутні vision artifacts → відповідь користувачу + телеграм менеджеру.


## 1.6. Принципи оркестрації (LangGraph)

- Вузли = транспорт + перевірки
- Вся “інтелектуальна” логіка повинна бути в агентах або інструментах
- FSM transitions мають бути явними

---

# 2) Технічний чек‑лист якості (anti‑hallucination)

## 2.1. Жорсткі правила
- Нуль UA‑рядків у коді (крім коментарів/логів)
- Тексти тільки через Registry
- Ціни/каталог тільки з БД або SSOT‑yaml


## 2.2. Контракт відповіді
- Pydantic‑модель завжди валідна
- Messages лише plain text (без Markdown)
- Products — тільки з каталогу


## 2.3. Динамічний контекст
- В агента має бути доступ до:
  - каталогу
  - стану діалогу
  - памʼяті (memory)
- Заборонено “вигадувати” дані


## 2.4. Інструменти
- LLM не повинен "вгадувати" ціни, моделі, розміри
- Для цього існують tools / services
- Всі критичні дії мають йти через інструмент


## 2.5. Валідація і пост‑перевірки
- Перевірка price/size/sku перед показом клієнту
- Якщо дані не співпадають → fallback + ескалація


## 2.6. Стратегія деградації
- Якщо API/BД недоступні → fallback
- Якщо артефакти відсутні → escalation


## 2.7. Моніторинг
- Логи для latency, failures, retries
- Метрики на validation fail і escalation


## 2.8. Тестові критерії
- rg по кирилиці у src/*.py == 0
- verify_registry.py == PASS
- Vision артефакти присутні

---

# 3) Правила контенту (snippets / fallbacks / intents / system_messages)

## 3.1. Snippets (data/prompts/system/snippets.md)

Призначення:
- Діалоги, відповіді менеджера, шаблони

Правила:
- 1 думка = 1 бабл
- Вставляти лише “по сенсу”
- Не змінювати правила оплати та реквізити


## 3.2. Fallbacks (data/prompts/system/fallbacks.md)

Призначення:
- Усі помилки, таймаути, аварійні відповіді

Правила:
- Людський тон
- Мінімум технічних деталей
- Якщо критична помилка → escalation


## 3.3. Intents (data/prompts/system/intents.md)

Призначення:
- Патерни для intent detection

Правила:
- Короткі ключі
- Згруповані по intent
- Без зайвих слів


## 3.4. System Messages (data/prompts/system/system_messages.md)

Призначення:
- /start, /restart, системні відповіді
- Повідомлення менеджерам

Правила:
- Чітко, коротко, без зайвого


## 3.5. Форматування
- Заголовок завжди ### KEY_NAME
- Бабли відділені ---
- Не вставляти Markdown у відповіді для користувача


---

# 4) Як перевіряти, що все працює

1) Перевірка на кирилицю в коді:
rg -n "[А-Яа-яІіЇїЄє]" src -g "*.py"

2) Перевірка registry:
python src/verify_registry.py

3) Vision артефакти:
- data/vision/generated/model_rules.yaml
- data/vision/generated/test_set.json

4) Флоу тест:
- Vision: немає match → escalation
- Payment: proof → THANK_YOU
- Offer: price mismatch → fallback

---

# 5) Основні правила команди

- Ніякого хардкоду текстів у .py
- Всі правки фраз робимо через .md
- Якщо змінюється логіка — додається тест або правило в Registry
- Контент‑редактори не чіпають код
- Реліз без перевірок = заборонено
