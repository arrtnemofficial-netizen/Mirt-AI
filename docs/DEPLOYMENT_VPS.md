# 🚀 MIRT AI - Деплой на VPS (Продакшн)

## Вимоги до VPS

- **ОС:** Ubuntu 22.04 LTS (рекомендовано)
- **RAM:** мінімум 2GB (рекомендовано 4GB)
- **CPU:** 2 cores
- **Диск:** 20GB SSD
- **Мережа:** Публічний IP або домен

---

## Крок 1: Підготовка сервера

```bash
# Оновлення системи
sudo apt update && sudo apt upgrade -y

# Встановлення залежностей
sudo apt install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx git

# Створення користувача для додатку
sudo useradd -m -s /bin/bash mirt
sudo usermod -aG sudo mirt
```

---

## Крок 2: Клонування репозиторію

```bash
# Переключитись на користувача mirt
sudo su - mirt

# Клонувати репозиторій
git clone https://github.com/YOUR_REPO/Mirt-AI.git
cd Mirt-AI

# Створити віртуальне оточення
python3.11 -m venv venv
source venv/bin/activate

# Встановити залежності
pip install -r requirements.txt
```

---

## Крок 3: Конфігурація (.env файл)

```bash
# Створити .env файл
nano .env
```

**Вміст .env:**
```env
# OpenAI
OPENAI_API_KEY=sk-your-openai-key

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# ManyChat
MANYCHAT_API_KEY=your-manychat-api-key
MANYCHAT_VERIFY_TOKEN=kL2nM4oP6qR8sT0uV1wX3yZ5aB7cD9eF1gH3iJ5kL7mN9
MANYCHAT_PUSH_MODE=true

# Telegram (опційно)
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Публічний URL (ваш домен)
PUBLIC_BASE_URL=https://your-domain.com
```

---

## Крок 4: Systemd сервіс

```bash
# Створити сервіс
sudo nano /etc/systemd/system/mirt-ai.service
```

**Вміст mirt-ai.service:**
```ini
[Unit]
Description=MIRT AI Webhook Server
After=network.target

[Service]
User=mirt
Group=mirt
WorkingDirectory=/home/mirt/Mirt-AI
Environment="PYTHONPATH=/home/mirt/Mirt-AI"
EnvironmentFile=/home/mirt/Mirt-AI/.env
ExecStart=/home/mirt/Mirt-AI/venv/bin/python src/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Активувати і запустити
sudo systemctl daemon-reload
sudo systemctl enable mirt-ai
sudo systemctl start mirt-ai

# Перевірити статус
sudo systemctl status mirt-ai
```

---

## Крок 5: Nginx + SSL

```bash
# Створити конфігурацію Nginx
sudo nano /etc/nginx/sites-available/mirt-ai
```

**Вміст nginx конфігурації:**
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

```bash
# Активувати сайт
sudo ln -s /etc/nginx/sites-available/mirt-ai /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Отримати SSL сертифікат (Let's Encrypt)
sudo certbot --nginx -d your-domain.com
```

---

## Крок 6: Перевірка

```bash
# Перевірити що сервер працює
curl https://your-domain.com/health

# Очікуваний результат:
# {"status":"ok","checks":{"supabase":"ok"}}
```

---

## Крок 7: Налаштування ManyChat

В ManyChat External Request вкажіть:

- **URL:** `https://your-domain.com/api/v1/messages`
- **Method:** POST
- **Headers:**
  - `X-API-Key: kL2nM4oP6qR8sT0uV1wX3yZ5aB7cD9eF1gH3iJ5kL7mN9`
  - `Content-Type: application/json`

---

## Моніторинг логів

```bash
# Логи сервера в реальному часі
sudo journalctl -u mirt-ai -f

# Останні 100 рядків логів
sudo journalctl -u mirt-ai -n 100
```

---

## Оновлення коду

```bash
cd /home/mirt/Mirt-AI
git pull origin main
sudo systemctl restart mirt-ai
```

---

## Troubleshooting

### Сервер не стартує
```bash
sudo journalctl -u mirt-ai -n 50 --no-pager
```

### Помилка 502 Bad Gateway
```bash
# Перевірити чи сервер слухає порт
sudo netstat -tlnp | grep 8000
```

### Перезапуск всього
```bash
sudo systemctl restart mirt-ai
sudo systemctl restart nginx
```
