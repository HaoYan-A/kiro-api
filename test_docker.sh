#!/bin/bash
# Docker API Test Script

BASE_URL="http://localhost:8080"
API_KEY="sk-kiro-yanhao"

echo "=============================================="
echo "Kiro API Docker Test"
echo "=============================================="
echo ""

# 1. Health check
echo "--- 1. Health Check ---"
curl -s $BASE_URL/health
echo ""
echo ""

# 2. Frontend page
echo "--- 2. Frontend Page ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" $BASE_URL/)
echo "GET / : HTTP $STATUS"
if [ "$STATUS" = "200" ]; then
    echo "Frontend: OK"
else
    echo "Frontend: FAILED"
fi
echo ""

# 3. Admin API (without auth - should fail)
echo "--- 3. Admin API (no auth) ---"
RESULT=$(curl -s $BASE_URL/admin/accounts)
echo "GET /admin/accounts: $RESULT"
echo ""

# 4. Admin API (with auth)
echo "--- 4. Admin API (with auth) ---"
curl -s -u admin:admin123 $BASE_URL/admin/accounts
echo ""
echo ""

# 5. Chat API
echo "--- 5. Chat API Test ---"
RESPONSE=$(curl -s -X POST $BASE_URL/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"model":"claude-sonnet-4-20250514","max_tokens":50,"messages":[{"role":"user","content":"Reply with: Docker test OK!"}]}')

echo "Response:"
echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('content',[{}])[0].get('text','No response'))" 2>/dev/null || echo "$RESPONSE"
echo ""

echo "=============================================="
echo "Test Complete"
echo "=============================================="
