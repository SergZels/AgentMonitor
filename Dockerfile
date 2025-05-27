FROM python:3.11-slim

# Встановлюємо необхідні системні пакети
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Створюємо робочу директорію
WORKDIR /app

# Копіюємо файл з залежностями
COPY requirements.txt .

# Встановлюємо Python залежності
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо код додатка
COPY telegram_multi_monitor.py .
COPY generate_session.py .

# Створюємо директорію для конфігурації та логів
RUN mkdir -p /app/config /app/logs

# Створюємо користувача для безпеки
RUN useradd -m -u 1000 telegram_user && \
    chown -R telegram_user:telegram_user /app

USER telegram_user

# Змінні оточення
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Команда за замовчуванням
CMD ["python", "AgentMonitor.py"]