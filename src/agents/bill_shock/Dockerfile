FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8006

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/bill_shock/Dockerfile .`
COPY src/agents/bill_shock/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/bill_shock/ src/agents/bill_shock/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/demo_billing_data.json src/data/
COPY src/data/15minute_data_sample.csv src/data/

EXPOSE 8006
CMD ["uvicorn", "src.agents.bill_shock.bill_shock_service:app", "--host", "0.0.0.0", "--port", "8006"]
