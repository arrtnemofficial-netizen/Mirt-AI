# FSM Transition Table

Офіційне джерело станів і переходів — `src/core/state_machine.py` та `src/agents/langgraph/state.py`.
Таблиця нижче показує, як `dialog_phase` мапиться на вузли LangGraph і які маршрути можливі після кожного стану.

| `dialog_phase`                     | Відповідальний вузол LangGraph | Можливі переходи                                                    | Призначення / тригери                                                                                 |
|------------------------------------|--------------------------------|---------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `INIT`                            | `moderation`                   | `DISCOVERY`, `ESCALATION`, `END`                                    | Антиспам + базова модерація. Якщо текст ок, переходимо до агентів, інакше ескалація/завершення.        |
| `DISCOVERY`                       | `agent`                        | `VISION_DONE`, `WAITING_FOR_SIZE`, `WAITING_FOR_COLOR`, `SIZE_COLOR_DONE` | Перший діалог з клієнтом: збір запиту, промпт-інженерія, запуск гілок Vision чи Commerce.             |
| `VISION_DONE`                     | `agent`                        | `WAITING_FOR_SIZE`, `WAITING_FOR_COLOR`, `SIZE_COLOR_DONE`, `ESCALATION` | Користувач надіслав фото, Vision завершився; агент просить зріст/колір або ескалює.                   |
| `WAITING_FOR_SIZE` / `WAITING_FOR_COLOR` | `agent`                  | `SIZE_COLOR_DONE`, `ESCALATION`                                     | Очікуємо уточнення щодо зросту/кольору; за потреби можемо ескалювати.                                 |
| `SIZE_COLOR_DONE`                 | `offer`                        | `OFFER_MADE`, `ESCALATION`                                          | Вузол пропозиції: будує кошик, підтягує каталог, запитує підтвердження.                               |
| `OFFER_MADE` / `PAYMENT_WAITING`  | `payment`                      | `UPSELL_OFFERED`, `COMPLETED`, `ESCALATION`, `PAYMENT_WAITING`      | Обробка оплати/чеки/пруфи. Використовує HITL, якщо активовано `ENABLE_PAYMENT_HITL`.                  |
| `UPSELL_OFFERED`                  | `upsell`                       | `COMPLETED`, `PAYMENT_WAITING`                                      | Додаємо додаткові товари, переключаємося назад у payment або завершуємо.                              |
| `COMPLETED`                       | `end`                          | `END`                                                               | Успішне завершення: надсилаємо фінальне повідомлення, лог стандартного happy-path.                   |
| `COMPLAINT` / `ESCALATION`        | `escalation`                   | `END`                                                               | Будь-яка ескалація (скарга, out-of-domain, Vision-помилка) — миттєвий перехід у людський супорт.     |

### Як читати таблицю

- **LangGraph node** — функція-вузол, визначена в `src/agents/langgraph/graph.py`.
- **Можливі переходи** — словники, які повертають `route_after_*` хелпери (наприклад, `get_agent_routes()`).
- **Dialog phase** зберігається в state (`ConversationState.dialog_phase`) і синхронізується з ManyChat/Supabase.

> Якщо додаєте нові фази, оновіть цю таблицю разом із:
> 1. `src/core/state_machine.py`
> 2. `docs/AGENTS_ARCHITECTURE.md`
> 3. `docs/OBSERVABILITY_RUNBOOK.md` (щоб описати нові сигнали/метрики)
