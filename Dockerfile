FROM python:3.11-slim

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Створюємо користувача для безпеки
RUN useradd -m -u 1000 telegram_user

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо requirements та встановлюємо Python залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код
COPY . .

# Створюємо необхідні директорії
RUN mkdir -p /app/logs /app/data /app/config && \
    chown -R telegram_user:telegram_user /app

# Переключаємося на нового користувача
USER telegram_user

# Відкриваємо порт для веб-інтерфейсу
EXPOSE 8000

# Змінні оточення
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/monitor/status')" || exit 1

# Команда запуску
CMD ["python", "mainAPI.py"]