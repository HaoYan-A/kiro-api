FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY server.py .
COPY config.yaml .
COPY static/ ./static/

# Create data directory
RUN mkdir -p /app/data/tokens

# Environment variables
ENV ADMIN_USERNAME=admin
ENV ADMIN_PASSWORD=admin123

# Expose port
EXPOSE 8080

# Run server
CMD ["python3", "server.py", "--port", "8080", "--host", "0.0.0.0"]
