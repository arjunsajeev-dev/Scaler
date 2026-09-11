# Optional. The orchestrator runs on the host with uvicorn; this image is unused
# unless you later choose to containerize it. Building it installs the `scaler` CLI
# so `docker exec <container> scaler health|list|log` works.

FROM python:3.12-slim-trixie

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml requirements.txt README.md ./
COPY src/ src/
COPY config/ config/

RUN pip install --no-cache-dir .

RUN useradd --system --uid 999 --no-create-home scaler \
    && chown -R scaler:scaler /app
USER scaler

EXPOSE 8000
CMD ["uvicorn", "scaler.main:app", "--host", "0.0.0.0", "--port", "8000"]
