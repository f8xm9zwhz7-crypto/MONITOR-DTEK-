FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY dtek_state.json . || true

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]