FROM python:3.13-slim

WORKDIR /app

# Install dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source is bind-mounted at /app via docker-compose; nothing else copied in.
CMD ["python", "--version"]
