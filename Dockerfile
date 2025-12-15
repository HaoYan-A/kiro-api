FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY server.py .
COPY config.yaml .

# Expose port
EXPOSE 8080

# Run server
CMD ["python", "server.py"]
