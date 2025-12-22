# Отчет об упавших тестах

**Дата:** 2025-12-20  
**Всего тестов:** 818  
**Пройдено:** 729  
**Упало:** 49  
**Ошибок при сборе:** 1

---

## Ошибки при сборе тестов

### 1. tests/manual/test_langgraph_full.py
**Ошибка:** `NameError: name 'pytest' is not defined`  
**Строка:** 201  
**Проблема:** Отсутствует импорт `pytest`  
**Решение:** Добавить `import pytest` в начало файла

---

## Упавшие тесты

### Тесты промптов (1)

#### tests/test_prompt.py::TestPromptStructure::test_has_escalation_rules
**Ошибка:** `assert 'L1' in prompt_text`  
**Проблема:** Тест ищет 'L1' в промпте, но его там нет  
**Решение:** Проверить, должен ли быть 'L1' в промпте или обновить тест

---

### Тесты workers (4)

#### tests/test_workers_integration.py::TestHealthTasks::test_health_check_task
**Ошибка:** `AttributeError: module 'src.services' has no attribute 'supabase_client'`  
**Проблема:** Неправильный импорт или путь к модулю  
**Решение:** Проверить правильный путь: `src.services.infra.supabase_client`

#### tests/test_workers_integration.py::TestSummarizationTasks::test_summarize_session_with_messages
**Ошибка:** `ModuleNotFoundError: No module named 'src.services.message_store'`  
**Проблема:** Неправильный путь к модулю  
**Решение:** Использовать `src.services.infra.message_store`

#### tests/test_workers_integration.py::TestFollowupTasks::test_followup_not_due
**Ошибка:** `ModuleNotFoundError: No module named 'src.services.message_store'`  
**Проблема:** Неправильный путь к модулю  
**Решение:** Использовать `src.services.infra.message_store`

#### tests/test_workers_integration.py::TestFollowupTasks::test_followup_triggered
**Ошибка:** `ModuleNotFoundError: No module named 'src.services.message_store'`  
**Проблема:** Неправильный путь к модулю  
**Решение:** Использовать `src.services.infra.message_store`

---

### Тесты схем агентов (3)

#### tests/unit/agents/test_agent_response_schema.py::TestSupportResponseContract::test_support_response_has_deliberation
**Ошибка:** `AssertionError: CONTRACT: SupportResponse should have 'deliberation' field`  
**Проблема:** В модели `SupportResponse` отсутствует поле `deliberation`  
**Решение:** Добавить поле `deliberation` в модель или обновить тест, если поле не требуется

#### tests/unit/agents/test_agent_response_schema.py::TestProductMatchContract::test_product_match_structure
**Ошибка:** `ValidationError: 3 validation errors for ProductMatch`  
**Поля:** `size`, `color`, `photo_url` - Field required  
**Проблема:** Тест создает ProductMatch без обязательных полей  
**Решение:** Обновить тест, чтобы включать все обязательные поля

#### tests/unit/agents/test_output_contract.py::TestSerialization::test_vision_response_to_dict
**Ошибка:** `ValidationError: 4 validation errors for ProductMatch`  
**Поля:** `id`, `size`, `color`, `photo_url` - Field required  
**Проблема:** Тест создает ProductMatch без обязательных полей  
**Решение:** Обновить тест, чтобы включать все обязательные поля

#### tests/unit/agents/test_output_contract.py::TestBackwardCompatibility::test_vision_response_with_product
**Ошибка:** `ValidationError: 2 validation errors for ProductMatch`  
**Поля:** `id`, `size` - Field required  
**Проблема:** Тест создает ProductMatch без обязательных полей  
**Решение:** Обновить тест, чтобы включать все обязательные поля

---

### Тесты конфигурации (3)

#### tests/unit/config/test_config.py::TestConfigLoads::test_payment_config_structure
**Ошибка:** `ModuleNotFoundError: No module named 'src.conf.payment_config'`  
**Проблема:** Модуль `payment_config` не существует  
**Решение:** Создать модуль или обновить тест, если конфигурация перенесена в другой модуль

#### tests/unit/config/test_config.py::TestConfigLoads::test_payment_config_values_valid
**Ошибка:** `ModuleNotFoundError: No module named 'src.conf.payment_config'`  
**Проблема:** Модуль `payment_config` не существует  
**Решение:** Создать модуль или обновить тест

#### tests/unit/config/test_config_safety.py::test_loop_guard_settings_sanity
**Ошибка:** `AttributeError: 'Settings' object has no attribute 'LOOP_GUARD_WARNING_THRESHOLD'`  
**Проблема:** В Settings отсутствует поле `LOOP_GUARD_WARNING_THRESHOLD`  
**Решение:** Добавить поле в Settings или удалить тест, если функциональность удалена

#### tests/unit/config/test_config_safety.py::test_loop_guard_invalid_values
**Ошибка:** `Failed: DID NOT RAISE ValidationError`  
**Проблема:** Тест ожидает, что валидация выбросит ошибку, но этого не происходит  
**Решение:** Проверить, должна ли быть валидация для этого поля

---

### Тесты моделей памяти (28)

#### tests/unit/models/test_memory_models.py::TestChildProfile::test_01_child_profile_defaults
**Ошибка:** `AttributeError: 'ChildProfile' object has no attribute 'body_type'`  
**Проблема:** В модели ChildProfile отсутствует поле `body_type`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestChildProfile::test_03_child_profile_age_validation_min
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию минимального возраста, но она не срабатывает  
**Решение:** Добавить валидацию возраста в модель

#### tests/unit/models/test_memory_models.py::TestChildProfile::test_04_child_profile_age_validation_max
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию максимального возраста, но она не срабатывает  
**Решение:** Добавить валидацию возраста в модель

#### tests/unit/models/test_memory_models.py::TestChildProfile::test_05_child_profile_height_validation_min
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию минимального роста, но она не срабатывает  
**Решение:** Добавить валидацию роста в модель

#### tests/unit/models/test_memory_models.py::TestChildProfile::test_06_child_profile_height_validation_max
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию максимального роста, но она не срабатывает  
**Решение:** Добавить валидацию роста в модель

#### tests/unit/models/test_memory_models.py::TestChildProfile::test_08_child_profile_body_type_literal
**Ошибка:** `AttributeError: 'ChildProfile' object has no attribute 'body_type'`  
**Проблема:** В модели ChildProfile отсутствует поле `body_type`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_16_logistics_defaults
**Ошибка:** `AttributeError: 'LogisticsInfo' object has no attribute 'delivery_type'`  
**Проблема:** В модели LogisticsInfo отсутствует поле `delivery_type`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_17_logistics_full
**Ошибка:** `AttributeError: 'LogisticsInfo' object has no attribute 'delivery_type'`  
**Проблема:** В модели LogisticsInfo отсутствует поле `delivery_type`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_18_logistics_delivery_types
**Ошибка:** `AttributeError: 'LogisticsInfo' object has no attribute 'delivery_type'`  
**Проблема:** В модели LogisticsInfo отсутствует поле `delivery_type`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_19_commerce_defaults
**Ошибка:** `AttributeError: 'CommerceInfo' object has no attribute 'avg_check'`  
**Проблема:** В модели CommerceInfo отсутствует поле `avg_check`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_20_commerce_full
**Ошибка:** `AttributeError: 'CommerceInfo' object has no attribute 'avg_check'`  
**Проблема:** В модели CommerceInfo отсутствует поле `avg_check`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_21_commerce_order_frequency_literals
**Ошибка:** `AttributeError: 'CommerceInfo' object has no attribute 'order_frequency'`  
**Проблема:** В модели CommerceInfo отсутствует поле `order_frequency`  
**Решение:** Добавить поле или обновить тест

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_22_commerce_avg_check_validation
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию avg_check, но она не срабатывает  
**Решение:** Добавить валидацию в модель

#### tests/unit/models/test_memory_models.py::TestLogisticsAndCommerce::test_23_commerce_total_orders_validation
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию total_orders, но она не срабатывает  
**Решение:** Добавить валидацию в модель

#### tests/unit/models/test_memory_models.py::TestUserProfile::test_28_user_profile_completeness_range
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию completeness, но она не срабатывает  
**Решение:** Добавить валидацию в модель

#### tests/unit/models/test_memory_models.py::TestFactModels::test_30_new_fact_importance_validation_min
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию минимальной важности, но она не срабатывает  
**Решение:** Добавить валидацию в модель

#### tests/unit/models/test_memory_models.py::TestFactModels::test_31_new_fact_importance_validation_max
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию максимальной важности, но она не срабатывает  
**Решение:** Добавить валидацию в модель

#### tests/unit/models/test_memory_models.py::TestFactModels::test_32_new_fact_surprise_validation
**Ошибка:** `Failed: DID NOT RAISE ValueError`  
**Проблема:** Тест ожидает валидацию surprise, но она не срабатывает  
**Решение:** Добавить валидацию в модель

#### tests/unit/models/test_memory_models.py::TestFactModels::test_37_fact_full_model
**Ошибка:** `ValidationError: id - Input should be a valid string [type=string_type, input_value=UUID(...), input_type=UUID]`  
**Проблема:** Модель Fact ожидает строку для id, но получает UUID  
**Решение:** Изменить тип поля id на UUID или добавить конвертацию

#### tests/unit/models/test_memory_models.py::TestFactModels::test_39_update_fact_model
**Ошибка:** `ValidationError: fact_id - Input should be a valid string [type=string_type, input_value=UUID(...), input_type=UUID]`  
**Проблема:** Модель UpdateFact ожидает строку для fact_id, но получает UUID  
**Решение:** Изменить тип поля fact_id на UUID или добавить конвертацию

#### tests/unit/models/test_memory_models.py::TestFactModels::test_40_delete_fact_model
**Ошибка:** `ValidationError: fact_id - Input should be a valid string [type=string_type, input_value=UUID(...), input_type=UUID]`  
**Проблема:** Модель DeleteFact ожидает строку для fact_id, но получает UUID  
**Решение:** Изменить тип поля fact_id на UUID или добавить конвертацию

#### tests/unit/models/test_memory_models.py::TestMemoryDecision::test_43_memory_decision_with_updates
**Ошибка:** `ValidationError: fact_id - Input should be a valid string [type=string_type, input_value=UUID(...), input_type=UUID]`  
**Проблема:** Модель UpdateFact ожидает строку для fact_id, но получает UUID  
**Решение:** Изменить тип поля fact_id на UUID или добавить конвертацию

#### tests/unit/models/test_memory_models.py::TestMemoryDecision::test_46_memory_decision_complex
**Ошибка:** `ValidationError: fact_id - Input should be a valid string [type=string_type, input_value=UUID(...), input_type=UUID]`  
**Проблема:** Модель UpdateFact ожидает строку для fact_id, но получает UUID  
**Решение:** Изменить тип поля fact_id на UUID или добавить конвертацию

#### tests/unit/models/test_memory_models.py::TestMemoryContext::test_51_memory_context_to_prompt_empty
**Ошибка:** `AssertionError: assert 'MEMORY CONTEXT' == ''`  
**Проблема:** Тест ожидает пустую строку, но получает 'MEMORY CONTEXT'  
**Решение:** Обновить метод `to_prompt()` чтобы возвращать пустую строку для пустого контекста

#### tests/unit/models/test_memory_models.py::TestMemoryContext::test_52_memory_context_to_prompt_with_child
**Ошибка:** `AssertionError: assert 'Дитя:' in prompt_text`  
**Проблема:** Тест ожидает 'Дитя:' в выводе, но его там нет  
**Решение:** Обновить метод `to_prompt()` или обновить тест

#### tests/unit/models/test_memory_models.py::TestMemoryContext::test_55_memory_context_to_prompt_limits_facts
**Ошибка:** `AssertionError: assert 16 <= 10`  
**Проблема:** Тест ожидает максимум 10 фактов, но получает 16  
**Решение:** Исправить лимит фактов в методе `to_prompt()`

#### tests/unit/models/test_memory_models.py::TestEdgeCases::test_68_rounding_importance
**Ошибка:** `AssertionError: assert 0.666666 == 0.67`  
**Проблема:** Тест ожидает округление до 0.67, но получает 0.666666  
**Решение:** Добавить округление в модель или обновить тест

#### tests/unit/models/test_memory_models.py::TestEdgeCases::test_70_uuid_serialization
**Ошибка:** `ValidationError: id - Input should be a valid string [type=string_type, input_value=UUID(...), input_type=UUID]`  
**Проблема:** Модель Fact ожидает строку для id, но получает UUID  
**Решение:** Изменить тип поля id на UUID или добавить конвертацию

---

### Тесты состояний (1)

#### tests/unit/state/test_guard_scenarios.py::test_repeat_height_phase_forces_offer_state
**Ошибка:** `AssertionError: assert 'STATE_3_SIZE_COLOR' == 'STATE_4_OFFER'`  
**Проблема:** Тест ожидает переход в STATE_4_OFFER, но остается в STATE_3_SIZE_COLOR  
**Решение:** Проверить логику guardrails для повторного ввода роста

---

### Тесты vision (1)

#### tests/unit/vision/test_hash_guard.py::test_vision_duplicate_hash_guard
**Ошибка:** `AssertionError: assert 0 == 1`  
**Проблема:** Тест ожидает, что `run_vision` будет вызван 1 раз, но не вызывается  
**Решение:** Проверить логику hash guard в vision node

---

## Резюме

### Категории проблем:

1. **Отсутствующие поля в моделях** (15 тестов)
   - ChildProfile: `body_type`
   - LogisticsInfo: `delivery_type`
   - CommerceInfo: `avg_check`, `order_frequency`
   - SupportResponse: `deliberation`

2. **Отсутствующая валидация** (10 тестов)
   - Валидация возраста, роста в ChildProfile
   - Валидация в CommerceInfo, UserProfile, NewFact

3. **Неправильные типы данных** (6 тестов)
   - UUID vs string для `id` и `fact_id` в моделях памяти

4. **Неправильные импорты** (5 тестов)
   - `src.services.message_store` → `src.services.infra.message_store`
   - `src.services.supabase_client` → `src.services.infra.supabase_client`
   - `src.conf.payment_config` - модуль не существует

5. **Отсутствующие обязательные поля в тестах** (4 теста)
   - ProductMatch требует `id`, `size`, `color`, `photo_url`

6. **Логика и форматирование** (4 теста)
   - MemoryContext.to_prompt() форматирование
   - Guard scenarios переходы состояний
   - Vision hash guard логика

7. **Отсутствующие модули/атрибуты** (3 теста)
   - `pytest` не импортирован
   - `LOOP_GUARD_WARNING_THRESHOLD` отсутствует в Settings
   - Промпт не содержит 'L1'

---

## Рекомендации по приоритетам

### Критично (блокируют функциональность):
1. Исправить импорты в тестах workers
2. Исправить типы UUID в моделях памяти
3. Добавить обязательные поля в ProductMatch тесты

### Высокий приоритет:
4. Добавить отсутствующие поля в модели
5. Добавить валидацию в модели
6. Исправить логику guard scenarios и vision hash guard

### Средний приоритет:
7. Исправить форматирование MemoryContext
8. Обновить тесты промптов
9. Создать payment_config модуль или обновить тесты

