FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY data/ ./data/

EXPOSE 5566

CMD ["gunicorn", "--bind", "0.0.0.0:5566", "--workers", "2", "--threads", "4", "--timeout", "30", "app:app"]
