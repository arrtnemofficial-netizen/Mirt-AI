<!-- version: 1.0 -->

# System Messages and Notifications
This file contains technical bot messages, manager notifications, and moderation responses.

### BOT_START_REPLY
Можемо почати спілкування!

### BOT_RESTART_REPLY
Сесію повністю перезапустила 🤍 Можемо почати з нуля. Надішліть фото або запитання.

### NOTIFY_MANAGER_ALERT
🚨 Потрібен менеджер

### NOTIFY_MANAGER_REASON
Причина: {reason}

### NOTIFY_MANAGER_SESSION
Session: `{session_id}`

### NOTIFY_MANAGER_TRACE
Trace: `{trace_id}`

### NOTIFY_MANAGER_STAGE
Стадія: {dialog_phase} / {current_state}

### NOTIFY_MANAGER_INTENT
Intent: {intent}

### NOTIFY_MANAGER_CLIENT
Клієнт: {who}

### NOTIFY_MANAGER_DELIVERY
Доставка: {where}

### NOTIFY_MANAGER_PAYMENT
Оплата: {payment_info}

### NOTIFY_MANAGER_PROOF_URL
Пруф URL: {url}

### NOTIFY_MANAGER_PRODUCTS_HEADER
Товари:

### NOTIFY_MANAGER_LAST_USER_MSG
Останнє від клієнта:

### UPSELL_CRM_QUEUED
🔄 Замовлення відправлено до CRM системи
---
✅ Очікуємо підтвердження від оператора

### UPSELL_CRM_CREATED
✅ Замовлення успішно створено в CRM

### UPSELL_CRM_EXISTS
ℹ️ Замовлення вже існує в CRM

### UPSELL_CRM_FAILED
⚠️ Проблема з створенням замовлення в CRM: {error}

### ESCALATION_REASON_RETRIES
Перевищено кількість спроб

### ESCALATION_REASON_MODERATION
Модерація

### ESCALATION_REASON_OPERATOR
Потрібна допомога оператора

### MODERATION_INJECTION_REASON
Виявлено спробу маніпуляції інструкціями.

### MODERATION_FORBIDDEN_REASON
Небезпечний вміст у повідомленні користувача.

### MODERATION_REDACTED_TEXT
### ADMIN_CRITICAL_ERROR
🚨 **CRITICAL ERROR**
Session: `{session_id}`
Failed to save order/CRM!
Error: {error}
