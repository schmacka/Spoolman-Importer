FROM python:3.12-slim

# zbar is required by pyzbar for barcode/QR scanning
RUN apt-get update \
    && apt-get install -y --no-install-recommends libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY addon/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY addon/app/ ./app/

RUN mkdir -p /data

ENV DATA_PATH=/data \
    SPOOLMAN_URL=http://localhost:7912 \
    ANTHROPIC_API_KEY="" \
    SPOOLMAN_API_KEY=""

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
