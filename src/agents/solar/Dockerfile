FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8010

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/solar/Dockerfile .`
COPY src/agents/solar/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/solar/ src/agents/solar/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/demo_billing_data.json src/data/
COPY src/data/15minute_data_sample.csv src/data/

EXPOSE 8010
CMD ["uvicorn", "src.agents.solar.solar_monitoring_service:app", "--host", "0.0.0.0", "--port", "8010"]
