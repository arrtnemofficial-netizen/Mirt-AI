# План прибирання "test debt" (хардкод/дублювання) після стабілізації checkpointer

Ціль: зберегти робочу поведінку гілки `test`, але прибрати ризики для prod: хардкод, дублювання, приховані залежності від env, і “магічні” фолбеки.

## 1) Конфіг і середовища (найбільший ризик)

- **Єдине джерело істини**: всі URL/секрети лише через env (`DATABASE_URL_POOLER`, `DATABASE_URL`, `REDIS_URL`, тощо).
- **Заборонити** генерацію `DATABASE_URL` із `SUPABASE_API_KEY` у prod/staging (дозволено лише dev).
- **Явно описати** політику warmup:
  - warmup best-effort (не блокує сервіс)
  - `CHECKPOINTER_WARMUP_REQUIRED=true` — тільки якщо впевнені у стабільності DB

## 2) Checkpointer: прибрати розходження між гілками

- Винести `get_postgres_checkpointer()` у стабільний модуль і **не дублювати** реалізацію в `test`.
- Стандартизувати:
  - `prepare_threshold=None`
  - pool `open=False` + on-demand open перед будь-якою DB операцією
  - health-check `SELECT 1`
  - таймаути через env

## 3) Логіка агента: зняти тимчасові “латки”

- Зібрати всі “гарячі” правки (regex, парсинг з росту/розміру, тощо) у **одне місце** (utils) з тестами.
- Прибрати дублювання коду між нодами (`agent`, `router`, `payment`) через спільні хелпери.
- Винести “магічні” константи (ліміти повідомлень, caps, таймаути) у `settings`.

## 4) Тести (мінімально необхідні)

- **Unit**: парсинг height/size, редьюсери state, `_determine_dialog_phase`.
- **Integration** (без реального Supabase): mock checkpointer + кілька turns.
- **Smoke**: cold start + перший webhook (щоб не ловити ManyChat timeout).

## 5) Критерії готовності до prod

- Нема `INTRANS`/discard циклів у логах пулу.
- Перший webhook не падає і не виходить за таймаут ManyChat.
- Після рестарту сервісу thread/state відновлюється (persistence працює).


