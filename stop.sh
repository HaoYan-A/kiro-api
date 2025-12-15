#!/bin/bash
# Kiro API Stop Script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Stopping Kiro API services..."

# Stop nginx
if [ -f /tmp/kiro-api-nginx.pid ]; then
    nginx -s stop -c "$SCRIPT_DIR/nginx.conf" 2>/dev/null
    echo "Nginx stopped."
fi

# Stop backend
pkill -f "python3 server.py" 2>/dev/null
echo "Backend stopped."

echo "All services stopped."
