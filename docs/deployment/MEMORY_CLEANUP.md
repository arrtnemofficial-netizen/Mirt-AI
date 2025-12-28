# Memory Cleanup - Deployment Guide

## Огляд

Memory cleanup деактивує expired факти з таблиці `mirt_memories` (встановлює `is_active = FALSE` для записів з `expires_at < now()`).

**Важливо:** Це не критично для роботи системи, але без cleanup таблиця буде рости.

## Способи запуску

### 1. CLI скрипт (рекомендовано)

```bash
# Тільки cleanup
python -m src.services.memory.tasks --task cleanup

# Повний цикл (decay + cleanup + summaries)
python -m src.services.memory.tasks --task full

# Тільки time decay
python -m src.services.memory.tasks --task decay

# Тільки summaries
python -m src.services.memory.tasks --task summaries --days 7
```

### 2. Railway Cron Job

Додайте в Railway новий сервіс з типом "Cron Job":

```yaml
# railway.json або через UI
{
  "cron": {
    "schedule": "0 4 * * *",  # Щодня о 4:00 UTC
    "command": "python -m src.services.memory.tasks --task cleanup"
  }
}
```

### 3. Docker Healthcheck / Init Container

```dockerfile
# В Dockerfile або docker-compose.yml
HEALTHCHECK --interval=24h --timeout=300s --start-period=0s \
  CMD python -m src.services.memory.tasks --task cleanup || exit 1
```

### 4. Systemd Timer (Linux)

```ini
# /etc/systemd/system/memory-cleanup.service
[Unit]
Description=MIRT Memory Cleanup
After=network.target

[Service]
Type=oneshot
User=your-user
WorkingDirectory=/path/to/mirt-ai
ExecStart=/usr/bin/python3 -m src.services.memory.tasks --task cleanup
```

```ini
# /etc/systemd/system/memory-cleanup.timer
[Unit]
Description=Run Memory Cleanup Daily
Requires=memory-cleanup.service

[Timer]
OnCalendar=daily
OnCalendar=04:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable memory-cleanup.timer
sudo systemctl start memory-cleanup.timer
```

### 5. Kubernetes CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: memory-cleanup
spec:
  schedule: "0 4 * * *"  # Щодня о 4:00 UTC
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: your-mirt-ai-image
            command: ["python", "-m", "src.services.memory.tasks", "--task", "cleanup"]
          restartPolicy: OnFailure
```

## Рекомендований розклад

- **Cleanup expired:** Щодня о 4:00 UTC
- **Time decay:** Щодня о 3:00 UTC (опційно)
- **Generate summaries:** Щотижня (неділя о 5:00 UTC) (опційно)

## Перевірка

Після налаштування перевірте, що cleanup працює:

```bash
# Запустіть вручну
python -m src.services.memory.tasks --task cleanup

# Перевірте логи
# Має бути: "✅ Cleanup complete: X expired facts deactivated"
```

## Примітки

- Cleanup не видаляє записи фізично, тільки деактивує (`is_active = FALSE`)
- Якщо cleanup не запускається, система працює нормально, але таблиця росте
- Для production рекомендується налаштувати автоматичний запуск через cron/cronjob

