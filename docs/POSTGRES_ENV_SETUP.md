# PostgreSQL Environment Variables Setup

## Обов'язкові змінні для PostgreSQL

### Основне підключення

```bash
# Основна змінна для PostgreSQL (пріоритет 1)
DATABASE_URL=postgresql://postgres:password@host:5432/database

# Альтернативна змінна (використовується якщо DATABASE_URL порожня)
POSTGRES_URL=postgresql://postgres:password@host:5432/database
```

### Формат connection string

```
postgresql://[user]:[password]@[host]:[port]/[database]
```

**Приклад для Railway:**
```bash
DATABASE_URL=postgresql://postgres:ZxEqgWqgzcZNvMNwhYykInpyxKDjNitk@postgres.railway.internal:5432/railway
```

**Приклад для публічного Railway URL:**
```bash
DATABASE_URL=postgresql://postgres:password@containers-us-west-xxx.railway.app:5432/railway
```

### Опціональні налаштування пулу з'єднань

```bash
# Мінімальний розмір пулу (за замовчуванням: 1)
POSTGRES_POOL_MIN_SIZE=1

# Максимальний розмір пулу (за замовчуванням: 10)
POSTGRES_POOL_MAX_SIZE=10

# Максимальний час простою з'єднання в секундах (за замовчуванням: 30)
POSTGRES_POOL_MAX_IDLE=30
```

## Повний приклад .env файлу

```bash
# ============================================================================
# PostgreSQL Configuration
# ============================================================================
DATABASE_URL=postgresql://postgres:your_password@your_host:5432/your_database

# Опціонально: налаштування пулу
POSTGRES_POOL_MIN_SIZE=1
POSTGRES_POOL_MAX_SIZE=10
POSTGRES_POOL_MAX_IDLE=30

# ============================================================================
# Інші змінні (якщо потрібні)
# ============================================================================
# OpenAI / OpenRouter
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...

# Telegram
TELEGRAM_BOT_TOKEN=...

# ManyChat
MANYCHAT_VERIFY_TOKEN=...
```

## Як отримати connection string

### Railway

1. Відкрийте ваш Railway проект
2. Перейдіть до PostgreSQL service
3. Вкладка **Variables** → знайдіть `DATABASE_URL` або `POSTGRES_URL`
4. Скопіюйте значення

Або через Railway CLI:
```bash
railway variables
```

### Локальна PostgreSQL

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mirt_ai
```

### Docker PostgreSQL

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mirt_ai
```

## Перевірка підключення

Після налаштування перевірте підключення:

```bash
python scripts/test_postgres_stores.py
```

Або через Python:

```python
from src.services.postgres_pool import health_check
import asyncio

result = asyncio.run(health_check())
print("✅ PostgreSQL connected" if result else "❌ Connection failed")
```

## Важливо

1. **Пріоритет**: `DATABASE_URL` має пріоритет над `POSTGRES_URL`
2. **Безпека**: Ніколи не комітьте `.env` файли в git
3. **Формат**: Connection string повинен починатися з `postgresql://`
4. **Порт**: За замовчуванням PostgreSQL використовує порт `5432`

## Troubleshooting

### Помилка: "DATABASE_URL not set"
- Перевірте, що змінна встановлена: `echo $DATABASE_URL`
- Переконайтеся, що формат правильний: `postgresql://...`

### Помилка: "connection refused"
- Перевірте хост та порт
- Переконайтеся, що PostgreSQL запущений
- Перевірте firewall налаштування

### Помилка: "authentication failed"
- Перевірте username та password
- Переконайтеся, що користувач має права доступу до бази даних

