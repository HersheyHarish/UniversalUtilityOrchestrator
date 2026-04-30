FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8009

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/payment_risk/Dockerfile .`
COPY src/agents/payment_risk/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/payment_risk/ src/agents/payment_risk/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/demo_billing_data.json src/data/
COPY src/data/demo_payments.json src/data/

EXPOSE 8009
CMD ["uvicorn", "src.agents.payment_risk.payment_risk_service:app", "--host", "0.0.0.0", "--port", "8009"]
