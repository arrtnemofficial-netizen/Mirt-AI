# 🗄️ Storage Service — Фундамент (DAL)

> **Роль:** "Foundation" (Фундамент)
> **Відповідальність:** Низькорівневий доступ до бази даних (PostgreSQL), керування з'єднаннями та збереження стану.

Це **Data Access Layer (DAL)** всього проекту.
Всі інші сервіси (`Memory`, `Conversation`, `Summarization`) залежать від нього.

---

## 🏗️ Архітектура (Ironclad)

Тут реалізовано кілька патернів для максимальної надійності:

| Компонент | Файл | Функція |
| :--- | :--- | :--- |
| **Connection Pool** | `postgres_pool.py` | Використовує `psycopg_pool.AsyncConnectionPool`. Це запобігає відкриттю 1000 з'єднань і падінню бази. |
| **Session Store** | `postgres_store.py` | Зберігає стан FSM (`agent_sessions`). Має **In-Memory Fallback**: якщо база "ляже", бот продовжить працювати з пам'яті RAM. |
| **Message Store** | `postgres_message_store.py` | Зберігає історію чату (`mirt_messages`) і автоматично оновлює профіль юзера (`mirt_users`). |

---

## 🛡️ Особливості Надійності

### 1. Hybrid Session Strategy (`postgres_store.py`)
Це "родзинка" модуля.
При записі сесії (`save`):
1.  Моментально пише в RAM (`InMemorySessionStore`).
2.  Запускає запис в Postgres у **фоновому режимі** (Background Task).
*Результат:* Користувач не чекає, поки база відповість. Інтерфейс літає 🚀.

### 2. Auto-Updating User Profile (`postgres_message_store.py`)
Коли ми зберігаємо повідомлення, магазин "тихо" оновлює таблицю `users`:
*   `last_interaction_at` (щоб знала Summarization).
*   `username` / `instagram_username` (якщо вони змінились).

---

## ⚠️ Увага
Цей модуль містить **Singleton** пулу з'єднань.
Не намагайтесь створювати нові пули вручну — використовуйте `get_postgres_pool()`.
