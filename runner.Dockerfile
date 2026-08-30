FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt
WORKDIR /opt
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ docker.io \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1"
COPY backend/runner_service.py backend/runner_worker.py /opt/backend/
EXPOSE 8080
CMD ["uvicorn", "backend.runner_service:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
