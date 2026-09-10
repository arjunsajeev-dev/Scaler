FROM python:3.12-slim-trixie

WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.141.1 "uvicorn[standard]==0.52.4"
COPY app.py .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
