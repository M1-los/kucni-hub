#!/usr/bin/env bash
echo "Zaustavljam Kućni Hub..."
pkill -f "python3 server.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
echo "✓ Kućni Hub i Telegram bot su uspešno ugašeni."
