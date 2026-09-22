FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG INSTALL_OCR=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-ocr.txt requirements-prod.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --index-url "${PIP_INDEX_URL}" \
        -r requirements.txt \
        -r requirements-prod.txt \
    && if [ "${INSTALL_OCR}" = "true" ]; then \
        python -m pip install \
            --index-url "${PIP_INDEX_URL}" \
            -r requirements-ocr.txt; \
    fi

COPY . .
RUN mkdir -p instance/uploads instance/paddle_runtime

EXPOSE 8000

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "300", "--bind", "0.0.0.0:8000", "run:app"]
