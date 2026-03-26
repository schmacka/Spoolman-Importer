ARG BUILD_FROM
FROM $BUILD_FROM

# zbar for barcode/QR scanning (Alpine-based HA images)
RUN apk add --no-cache zbar-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /data

ENV DATA_PATH=/data

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
