#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Zaustavi prethodne ako postoje
pkill -f "python3 server.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null

echo "=================================================="
echo "🚀 Pokrećem Kućni Hub potpuno nezavisno..."

# Pokreni server u pozadini bez gašenja
nohup python3 "$DIR/server.py" > "$DIR/server.log" 2>&1 &
SERVER_PID=$!

# Pokreni Cloudflare tunel u pozadini
nohup "$DIR/bin/cloudflared" tunnel --url http://localhost:8000 > "$DIR/tunnel.log" 2>&1 &
TUNNEL_PID=$!

sleep 3

echo "✓ Server radi u pozadini (PID: $SERVER_PID)"
echo "✓ Tunel radi u pozadini (PID: $TUNNEL_PID)"
echo ""
echo "📱 Tvoj stalni link za telefon:"
grep -E "https://[a-zA-Z0-9-]+\.trycloudflare\.com" "$DIR/tunnel.log" | tail -n 1
echo "=================================================="
echo "Sada možeš zatvoriti i ugasiti ovaj prozor, server nastavlja da radi!"
