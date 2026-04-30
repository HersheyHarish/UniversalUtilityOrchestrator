FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8001

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/billing/Dockerfile .`
COPY src/agents/billing/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/billing/ src/agents/billing/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/demo_billing_data.json src/data/
COPY src/data/policies/ src/data/policies/
COPY src/data/vector_store/ src/data/vector_store/

EXPOSE 8001
CMD ["uvicorn", "src.agents.billing.app:app", "--host", "0.0.0.0", "--port", "8001"]
