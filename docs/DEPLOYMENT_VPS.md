# 🚀 Деплой на VPS (Ubuntu 22.04+)

> **Версія:** 5.0  
> **Статус:** ✅ Production Ready

---

## 🏗️ Architecture on VPS

```mermaid
flowchart TB
    subgraph VPS["🖥️ Ubuntu Server"]
        u[Nginx Reverse Proxy]
        
        subgraph App["📦 MIRT AI Service"]
            w[FastAPI (uvicorn)]
            c[Celery Worker]
            b[Celery Beat]
        end
        
        subgraph Data["💾 Local Data"]
            r[Redis]
            p[PostgreSQL (optional)]
        end
    end

    Internet -->|HTTPS/443| u
    u -->|HTTP/8000| w
    w --> r
    c --> r
    b --> r
```

---

## 📋 System Requirements

- **OS:** Ubuntu 22.04 LTS or newer
- **CPU:** 2+ vCPU
- **RAM:** 4GB+ (for AI inference/processing)
- **Disk:** 20GB+ NVMe

---

## 🛠️ Step-by-Step Installation

### 1. System Prep

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip redis-server nginx git
```

### 2. Project Setup

```bash
# Create user
sudo useradd -m -s /bin/bash mirt
sudo su - mirt

# Clone
git clone https://github.com/mirt-ua/mirt-ai.git /opt/mirt
cd /opt/mirt

# Venv
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables

Create `/opt/mirt/.env`:

```ini
PUBLIC_BASE_URL=https://ai.mirt.ua
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://localhost:6379/0
# ... other vars from .env.example
```

---

## ⚙️ Systemd Service Units

Create files in `/etc/systemd/system/`.

### 1. `mirt-web.service`

```ini
[Unit]
Description=MIRT AI Web Service (FastAPI)
After=network.target redis-server.service

[Service]
User=mirt
Group=mirt
WorkingDirectory=/opt/mirt
EnvironmentFile=/opt/mirt/.env
ExecStart=/opt/mirt/venv/bin/uvicorn src.server.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

### 2. `mirt-worker.service`

```ini
[Unit]
Description=MIRT AI Celery Worker
After=network.target redis-server.service

[Service]
User=mirt
Group=mirt
WorkingDirectory=/opt/mirt
EnvironmentFile=/opt/mirt/.env
ExecStart=/opt/mirt/venv/bin/celery -A src.workers.celery_app worker -l info -c 4 -Q llm,webhooks,followups,crm,summarization,default
Restart=always

[Install]
WantedBy=multi-user.target
```

### 3. `mirt-beat.service`

```ini
[Unit]
Description=MIRT AI Celery Beat
After=network.target redis-server.service

[Service]
User=mirt
Group=mirt
WorkingDirectory=/opt/mirt
EnvironmentFile=/opt/mirt/.env
ExecStart=/opt/mirt/venv/bin/celery -A src.workers.celery_app beat -l info
Restart=always

[Install]
WantedBy=multi-user.target
```

### Enable & Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mirt-web mirt-worker mirt-beat
```

---

## 🌐 Nginx Configuration

File: `/etc/nginx/sites-available/mirt`

```nginx
server {
    listen 80;
    server_name ai.mirt.ua;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Webhook timeouts
    location /webhooks/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_read_timeout 60s;
        proxy_connect_timeout 60s;
    }
}
```

Enable SSL with Certbot:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d ai.mirt.ua
```

---

## 🛡️ Security Hardening

- **UFW Firewall:**
  ```bash
  sudo ufw allow OpenSSH
  sudo ufw allow 'Nginx Full'
  sudo ufw enable
  ```
- **Fail2Ban:** Install to prevent brute-force.
- **Backups:** Setup cron job for `.env` backup.

---

## 📚 Пов'язані документи

| Документ | Опис |
|:---------|:-----|
| [DEPLOYMENT.md](DEPLOYMENT.md) | Загальний гайд по деплою |
| [CELERY.md](CELERY.md) | Налаштування воркерів |

---

> **Оновлено:** 20 грудня 2025, 13:45 UTC+2
