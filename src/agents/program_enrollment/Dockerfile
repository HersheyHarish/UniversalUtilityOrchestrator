FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8007

WORKDIR /app

# Build context is repo root: `docker build -f src/agents/program_enrollment/Dockerfile .`
COPY src/agents/program_enrollment/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agents/program_enrollment/ src/agents/program_enrollment/
COPY src/agents/shared/ src/agents/shared/
COPY src/data/demo_billing_data.json src/data/
COPY src/data/15minute_data_sample.csv src/data/

EXPOSE 8007
CMD ["uvicorn", "src.agents.program_enrollment.program_simulation_service:app", "--host", "0.0.0.0", "--port", "8007"]
