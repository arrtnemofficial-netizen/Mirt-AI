# Vision Layer Identity & Core Philosophy

## Mission Statement
Vision layer is the brand guardian at the sensory perimeter of Mirt-AI. Its purpose is to translate every incoming photo into structured, validated context **before** commercial flows (offer → payment → CRM) can act. It must err on the side of safety, never bluffing products or prices when factual confidence is missing.

## Core Principles

1. **Brand Safety Over Guesses**  
   - Hard conditions for escalation: no catalog match, low confidence, missing artifacts, repeated “no match”.  
   - Implementation refs:  
     - `src/agents/langgraph/nodes/vision/node.py` (escalation blocks, `_handle_missing_artifacts`).  
     - `src/services/infra/notification_service.py` (operator alerts).  

2. **Traceability & Observability First**  
   - Every Vision run logs latency, confidence, escalation reason.  
   - Metrics via `log_agent_step`, `track_metric`, `vision_node_duration`.  
   - Gaps: no global `vision_result_id`, duplicate notifications possible.  

3. **Data > LLM Assertions**  
   - Context assembled from deterministic artifacts (`data/vision/generated/*`).  
   - `VisionContextService` caches structured prompts; health tests ensure artifacts exist (`tests/integration/test_vision_health.py`).  
   - LLM output enriched with catalog DB via `enrich_product_from_db`.

## Interaction Blueprint
```
User photo → moderation → vision_node
  ↳ Context: VisionContextService + snippets
  ↳ LLM run (run_vision)
  ↳ Enrichment: builder/enricher
  ↳ Decision:
      - Happy path → offer_node
      - Escalation → NotificationService + HARD END
```

## Current Strengths
- Deterministic fallback messaging and escalation rules.
- Full artifact health-check suite (16 tests).
- Background notifications on critical errors.

## Known Gaps
- No idempotent identifier for Vision results (risk of duplicate downstream actions).
- No cache warmup/monitoring for VisionContextService.
- Missing integration test ensuring repeated low-confidence photos always escalate.

## Principle → Implementation Audit

| Принцип | Поточна реалізація | Прогалина/ризик |
| --- | --- | --- |
| Brand Safety Over Guesses | `vision_node` форсить HARD ескалацію при low confidence, відсутності артефактів, продукту поза каталогом. | Немає тесту, який доводить, що повторні no-match сценарії завжди ескалюють, і немає лічильника idempotency для ескалацій. |
| Traceability & Observability First | `log_agent_step`, `track_metric("vision_node_duration")`, trace_id у notification payload. | Відсутній глобальний `vision_result_id`, через що downstream-фази не можуть перевірити, чи результат уже обробляли. |
| Data > LLM Assertions | `VisionContextService` + `data/vision/generated/*` + `test_vision_health.py` гарантують цілісність артефактів, `enrich_product_from_db` синхронізує з каталогом. | Немає моніторингу TTL кешу та cron-а, що перевіряє, чи артефакти не застаріли; LLM усе ще може повторно “вигадати” продукт при повторному запуску. |

## Duplication & Conflict Risks

1. **Vision → Payment:** state може двічі накопичити ті самі `selected_products`, якщо користувач повторно надсилає ту саму фотку; відсутній hash guard (`vision_hash_processed`).  
2. **Payment → CRM:** `create_and_submit_order` покладається на `external_id`, але в БД немає `UNIQUE`-констрейнта, а отже можливі дублікати при ретраях Celery або повторному підтвердженні.  
3. **Notifications:** `_send_notification_background` не має idempotency key — повторні збої можуть спричинити SPAM менеджерам.

## Strategy Options

1. **Hash Guard (Quick Win)**  
   - Обчислювати hash від `session_id + image_url`, зберігати у metadata як `vision_hash_processed`.  
   - Блокувати повторне просування результату далі, якщо hash збігається.  
   - ETA: ~0.5 дня. Плюси: швидко, не потребує міграцій. Мінуси: не захистить від дублів, якщо інша сесія відправить ту саму фотку.

2. **Vision Results Ledger (Strategic)**  
   - Таблиця `vision_results` у Supabase: `vision_result_id`, hash, status, timestamps.  
   - Payment/CRM отримують `vision_result_id` і перевіряють, чи обробляли його.  
   - ETA: 2–3 дні (міграції, сервіс, тести). Плюси: повна трасовність, можливість відновлення. Мінуси: потребує підтримки схеми + API.

3. **Event Bus Dispatch (Long-Term)**  
   - Vision публікує `VISION_ANALYZED` у Redis/Kafka, downstream слухають і підтверджують.  
   - ETA: 1–2 тижні. Плюси: масштабованість, природна idempotency. Мінуси: інфраструктурна складність, потреба в DevOps.

**Поточний вибір:** реалізувати Hash Guard негайно (покращення готовності до ~97 %), паралельно спроєктувати Vision Ledger як наступний етап.

## Validation Plan

1. **Unit Tests**  
   - `test_vision_hash_guard`: двічі викликає `vision_node` з однаковим `image_url`, перевіряє, що другий виклик не додає нові продукти та виставляє `vision_hash_processed`.  
   - Тести на `VisionContextService`, які перевіряють поведінку кешу при TTL expiry.

2. **Integration Tests**  
   - Payment flow: мокнути `create_and_submit_order`, перевірити, що при повторі Vision hash виклик не відбувається.  
   - CRM integration: підтвердити, що `crm_order_result` з тим самим `vision_result_id` не створюється вдруге.

3. **Operational Checks**  
   - Моніторинг Telegram/NotificationService на дублікати (графік кількості алертів на сесію).  
   - SQL-констрейнт `UNIQUE (external_id)` у `crm_orders` + міграція з backfill.

## CRM Constraint Gameplan

1. **Інвентаризація дублів**  
   - SQL: `SELECT external_id, COUNT(*) FROM crm_orders GROUP BY external_id HAVING COUNT(*) > 1;`  
   - Для знайдених дублів: залишити найсвіжіший запис, решту архівувати у `crm_orders_duplicates`.

2. **Міграція**  
   - Файл `scripts/db/migrations/0XX_add_unique_external_id.sql`:  
     ```sql
     ALTER TABLE crm_orders
       ADD CONSTRAINT crm_orders_external_id_key UNIQUE (external_id);
     ```  
   - Після застосування — rerun Celery workers, щоб переконатись, що нові записи проходять.

3. **Ролбек-план**  
   - Видалити constraint, відновити архівовані рядки з `crm_orders_duplicates`.

## Recommendations Roadmap

1. **Short-Term (≤1 день)**  
   - Hash guard (виконано).  
   - Укріпити unit-тести Vision (`test_vision_hash_guard`).  
   - Підготувати/застосувати `UNIQUE (external_id)` міграцію.

2. **Mid-Term (2–4 дні)**  
   - Спроєктувати Vision Ledger (ADR + ERD).  
   - Додати інтеграційні тести payment/CRM з idempotency сценаріями.  
   - Верифікувати NotificationService на дублікати (ідемпотентні ключі).

3. **Long-Term (1–2 тижні)**  
   - Перейти на event-driven delivery (Redis/Kafka) для Vision результатів.  
   - Додати observability-дешборд (hash hits, duplicates, escalation rates).

## Next Steps (High-Level)
1. Introduce `vision_hash_processed` guard (quick win).  
2. Design Supabase `vision_results` ledger with unique IDs.  
3. Extend tests to cover duplicate submissions and notification idempotency.
