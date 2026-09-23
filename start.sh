#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# Universal Media Downloader — Ishga tushirish skripti
# ─────────────────────────────────────────────────────────────────

set -e

echo "================================================"
echo "  🎯 Universal Media Downloader v2.0"
echo "================================================"
echo ""

# Check Python
python3 --version || { echo "❌ Python3 kerak!"; exit 1; }

# Check ffmpeg
ffmpeg -version > /dev/null 2>&1 && echo "✅ ffmpeg topildi" || {
  echo "⚠️  ffmpeg topilmadi. Ba'zi formatlar ishlamasligi mumkin."
  echo "   Ubuntu/Debian: sudo apt install ffmpeg"
  echo "   macOS: brew install ffmpeg"
}

# Install dependencies
echo ""
echo "📦 Kutubxonalar o'rnatilmoqda..."
pip install --break-system-packages -q -r requirements.txt

echo ""
echo "✅ Hamma narsa tayyor!"
echo ""
echo "================================================"
echo "  🌐 Web interfeys:  http://localhost:8000"
echo "  📖 API Docs:        http://localhost:8000/api/docs"
echo "  💊 Health check:    http://localhost:8000/api/health"
echo "================================================"
echo ""

# Start server
cd "$(dirname "$0")"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
