FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/anomaly/Dockerfile .`
COPY src/agents/anomaly/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/anomaly/ src/agents/anomaly/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/15minute_data_sample.csv src/data/
COPY src/data/demo_billing_data.json src/data/

EXPOSE 8000
CMD ["uvicorn", "src.agents.anomaly.anomaly_service:app", "--host", "0.0.0.0", "--port", "8000"]
