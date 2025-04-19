# Этап сборки
FROM python:3.10-slim as builder

WORKDIR /app

# Устанавливаем зависимости для сборки
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Обновляем pip и устанавливаем wheel
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Копируем requirements.txt
COPY requirements.txt .

# Создаем все wheel файлы (включая зависимости)
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# Финальный этап
FROM python:3.10-slim

WORKDIR /app

# Копируем requirements.txt и wheels
COPY requirements.txt .
COPY --from=builder /app/wheels /wheels

# Устанавливаем зависимости из wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels

# Создаем директорию для данных
RUN mkdir -p /app/data

# Копируем код проекта
COPY . .

# Устанавливаем переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Запускаем бота
CMD ["python", "main.py"]