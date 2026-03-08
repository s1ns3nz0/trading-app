FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Health check endpoint (lightweight HTTP server via asyncio)
EXPOSE 8080

CMD ["python", "-m", "app.main"]
