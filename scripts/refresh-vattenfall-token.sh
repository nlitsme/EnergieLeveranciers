#!/bin/bash
# Vattenfall token refresh helper
# Token expires every 2 hours, so you'll need to do this regularly.
#
# Usage:
#   ./scripts/refresh-vattenfall-token.sh <new_token>
#
# Get a fresh token:
#   1. Open https://www.vattenfall.nl/mijn-vattenfall/ in Firefox
#   2. DevTools (F12) → Network tab
#   3. Filter: consumptions
#   4. Click any request to the API
#   5. Scroll to "Request Headers" → find "Authorization: Bearer eyJ..."
#   6. Copy everything after "Bearer " (the full JWT token)
#   7. Run: ./scripts/refresh-vattenfall-token.sh <paste_token_here>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

if [ $# -lt 1 ]; then
    echo "❌ Usage: $0 <new_token>"
    echo ""
    echo "Get a fresh token from the browser:"
    echo "  1. Open https://www.vattenfall.nl/mijn-vattenfall/"
    echo "  2. DevTools → Network → filter 'consumptions'"
    echo "  3. Click a request → copy 'Authorization: Bearer ***' value"
    echo "  4. Run: $0 eyJraWQ...<paste token here>"
    exit 1
fi

NEW_TOKEN="$1"

# Check if .env exists
if [ ! -f "$ENV_FILE" ]; then
    echo "⚠️  No .env file found at $ENV_FILE"
    echo "Creating one..."
    touch "$ENV_FILE"
fi

# Update or add VATTENFALL_AUTH_TOKEN
if grep -q "^VATTENFALL_AUTH_TOKEN=" "$ENV_FILE"; then
    # Check if it's a complex token (multiple lines, special chars)
    # Use sed with a different delimiter to handle special chars in JWT
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|^VATTENFALL_AUTH_TOKEN=.*|VATTENFALL_AUTH_TOKEN=$NEW_TOKEN|" "$ENV_FILE"
    else
        # Linux
        sed -i "s|^VATTENFALL_AUTH_TOKEN=.*|VATTENFALL_AUTH_TOKEN=$NEW_TOKEN|" "$ENV_FILE"
    fi
    echo "✅ Updated VATTENFALL_AUTH_TOKEN in .env"
else
    echo "VATTENFALL_AUTH_TOKEN=$NEW_TOKEN" >> "$ENV_FILE"
    echo "✅ Added VATTENFALL_AUTH_TOKEN to .env"
fi

# Quick test
echo ""
echo "🔍 Testing API with new token..."
curl -s -o /dev/null -w "  → HTTP %{http_code}\n" \
    "https://api.vattenfall.nl/api/mvf/consumptions/v0/consumptions/products/Electricity/Month?amount=1&endDate=2026-07-21" \
    -H "Authorization: Bearer $NEW_TOKEN" \
    -H "Ocp-Apim-Subscription-Key: ed989141b5c34d138dba4a3ce1dbe046" \
    -H "vf-context: 0025431819:003015847385" \
    -H "Accept: application/json, text/plain, */*" \
    -H "Origin: https://www.vattenfall.nl" \
    -H "Referer: https://www.vattenfall.nl/"

echo ""
echo "➡️  Now run: batterijberekening --provider vattenfall --force-fetch"