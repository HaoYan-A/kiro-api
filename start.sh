#!/bin/bash
# Kiro API Start Script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
BACKEND_PORT=${BACKEND_PORT:-8080}
NGINX_PORT=${NGINX_PORT:-8000}
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin123}

echo "=============================================="
echo "Kiro API Server"
echo "=============================================="
echo "Backend Port: $BACKEND_PORT"
echo "Nginx Port:   $NGINX_PORT"
echo "Admin User:   $ADMIN_USERNAME"
echo "=============================================="

# Export environment variables for backend
export ADMIN_USERNAME
export ADMIN_PASSWORD

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Stopping services..."
    if [ -f /tmp/kiro-api-nginx.pid ]; then
        nginx -s stop -c "$SCRIPT_DIR/nginx.conf" 2>/dev/null
    fi
    pkill -f "python3 server.py" 2>/dev/null
    echo "Services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend
echo "Starting backend server..."
python3 server.py --port $BACKEND_PORT &
BACKEND_PID=$!
sleep 2

# Check if backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "ERROR: Backend failed to start"
    exit 1
fi

# Start nginx
echo "Starting nginx..."
nginx -c "$SCRIPT_DIR/nginx.conf"

if [ $? -ne 0 ]; then
    echo "ERROR: Nginx failed to start"
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

echo ""
echo "=============================================="
echo "Services started successfully!"
echo ""
echo "API Endpoints:"
echo "  http://localhost:$NGINX_PORT/v1/messages"
echo "  http://localhost:$NGINX_PORT/claude/v1/messages"
echo ""
echo "Admin Panel:"
echo "  http://localhost:$NGINX_PORT/"
echo "  Login: $ADMIN_USERNAME / [password]"
echo ""
echo "Press Ctrl+C to stop"
echo "=============================================="

# Wait for backend process
wait $BACKEND_PID
