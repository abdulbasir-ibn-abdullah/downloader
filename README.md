# 🎯 Universal Media Downloader Pro

YouTube, Instagram, TikTok, Twitter/X, Facebook va **1000+ sayt**dan
video, audio, foto, reels, stories, playlist yuklovchi tizim.

## 🚀 Tez ishga tushirish

```bash
# 1. Papkaga kiring
cd medialoader/

# 2. Skriptni ishga tushiring (o'zi hamma narsani o'rnatadi)
bash start.sh

# YOKI qo'lda:
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 🌐 Manzillar

| Xizmat       | URL                            |
|-------------|--------------------------------|
| Web sahifa   | http://localhost:8000           |
| API Docs     | http://localhost:8000/api/docs  |
| Health check | http://localhost:8000/api/health|

## 📦 Yuklovchi dvigatellari (ketma-ketlik)

```
1. yt-dlp     → 1000+ sayt (asosiy)
      ↓ muvaffaqiyatsiz bo'lsa
2. gallery-dl → rasmlar/galereya uchun  
      ↓ muvaffaqiyatsiz bo'lsa
3. Direct HTTP → to'g'ridan-to'g'ri havolalar
```

## 🎯 API Endpointlar

### URL tahlil qilish
```http
POST /api/analyze
Content-Type: application/json

{
  "url": "https://youtube.com/watch?v=...",
  "quality": "best",
  "format": "auto"
}
```

### Yuklab olishni boshlash
```http
POST /api/download
Content-Type: application/json

{
  "url": "https://...",
  "quality": "1080p",     // best | 2160p | 1080p | 720p | 480p | 360p | audio_only
  "format": "mp4",         // auto | mp4 | mp3 | webm
  "subtitles": false,      // subtitrlarni ham yuklash
  "playlist": false        // playlist bo'lsa hammani yuklash
}
```

### Status tekshirish
```http
GET /api/status/{task_id}
```

### Faylni olish
```http
GET /download/{task_id}/{filename}
```

## 🔒 Xavfsizlik

- **Rate limiting**: IP boshiga minutiga max 10 so'rov
- **URL filterlash**: localhost, internal IP, zararli domenlar bloklanadi
- **Path traversal himoya**: fayllar faqat belgilangan papkadan
- **Fayl hajm chekovi**: max 2GB
- **Avtomatik tozalash**: 2 soat eski fayllar o'chiriladi

## 🌍 Qo'llab-quvvatlanan platformalar

YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit,
SoundCloud, Vimeo, Dailymotion, Pinterest, Twitch, Telegram,
LinkedIn, Bilibili, NicoNico, VK, Odnoklassniki, Streamable,
Gfycat, Tenor, Giphy, Imgur va **1000+ boshqa sayt**

## 📋 Talablar

- Python 3.9+
- ffmpeg (video birlashtirish uchun, tavsiya etiladi)
- Internet ulanishi
- Linux/macOS/Windows

## 🐛 Muammolar

```bash
# yt-dlp yangilash
pip install --break-system-packages --upgrade yt-dlp

# Log ko'rish
tail -f medialoader/logs/app.log
```
