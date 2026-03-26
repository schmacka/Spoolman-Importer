ARG BUILD_FROM
FROM $BUILD_FROM

# python3 + pip (base images don't include Python; base-python images lack bashio)
# zbar for barcode/QR scanning
RUN apk add --no-cache python3 py3-pip zbar-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /data

ENV DATA_PATH=/data

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
