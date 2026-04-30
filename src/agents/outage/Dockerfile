FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8005

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/outage/Dockerfile .`
COPY src/agents/outage/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/outage/ src/agents/outage/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/demo_outages.json src/data/
COPY src/data/demo_billing_data.json src/data/

EXPOSE 8005
CMD ["uvicorn", "src.agents.outage.outageDetectionAgent:app", "--host", "0.0.0.0", "--port", "8005"]
