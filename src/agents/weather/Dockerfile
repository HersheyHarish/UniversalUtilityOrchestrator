FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8004

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/weather/Dockerfile .`
COPY src/agents/weather/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/weather/ src/agents/weather/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/demo_billing_data.json src/data/

EXPOSE 8004
CMD ["uvicorn", "src.agents.weather.weatherContextAgent:app", "--host", "0.0.0.0", "--port", "8004"]
