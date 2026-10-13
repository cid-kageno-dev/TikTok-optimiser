FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=5000 MAX_UPLOAD_MB=2048
EXPOSE 5000
CMD ["sh", "-c", "gunicorn --workers 1 --threads 4 --timeout 3600 --bind 0.0.0.0:${PORT} app:app"]
