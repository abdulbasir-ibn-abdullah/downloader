"""
🎯 Universal Media Downloader - FastAPI Backend
Supports: YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit,
          SoundCloud, Vimeo, Dailymotion, Pinterest, Twitch, and 1000+ sites
"""

import os
import re
import json
import uuid
import time
import asyncio
import hashlib
import logging
import mimetypes
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
from urllib.parse import urlparse

import aiofiles
import aiohttp
import requests
import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl, field_validator
from contextlib import asynccontextmanager

# ─── Directories ─────────────────────────────────────────────────────────────
# BASE_DIR = Path("/home/claude/medialoader")
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
TEMP_DIR = BASE_DIR / "temp"
LOG_DIR = BASE_DIR / "logs"
MAX_FILE_AGE_HOURS = 2
MAX_FILE_SIZE_MB = 2000

# Papkalarni yaratish
LOG_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ─── Logging Setup ─────────────────────────────────────────────>
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
       # logging.FileHandler("/home/claude/medialoader/logs/app.l>
        logging.FileHandler(str(LOG_DIR / "app.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── Platform Detection ───────────────────────────────────────────────────────
PLATFORM_PATTERNS = {
    "youtube":      r"(youtube\.com|youtu\.be)",
    "instagram":    r"(instagram\.com|instagr\.am)",
    "tiktok":       r"(tiktok\.com|vm\.tiktok\.com)",
    "twitter":      r"(twitter\.com|x\.com|t\.co)",
    "facebook":     r"(facebook\.com|fb\.com|fb\.watch)",
    "reddit":       r"(reddit\.com|redd\.it)",
    "soundcloud":   r"(soundcloud\.com)",
    "vimeo":        r"(vimeo\.com)",
    "dailymotion":  r"(dailymotion\.com|dai\.ly)",
    "pinterest":    r"(pinterest\.com|pin\.it)",
    "twitch":       r"(twitch\.tv|clips\.twitch\.tv)",
    "telegram":     r"(t\.me|telegram\.me)",
    "linkedin":     r"(linkedin\.com)",
    "snapchat":     r"(snapchat\.com)",
    "tumblr":       r"(tumblr\.com)",
    "flickr":       r"(flickr\.com)",
    "bilibili":     r"(bilibili\.com|b23\.tv)",
    "niconico":     r"(nicovideo\.jp|nico\.ms)",
    "odnoklassniki":r"(ok\.ru|odnoklassniki\.ru)",
    "vk":           r"(vk\.com|vkontakte\.ru)",
    "streamable":   r"(streamable\.com)",
    "gfycat":       r"(gfycat\.com)",
    "tenor":        r"(tenor\.com)",
    "giphy":        r"(giphy\.com)",
    "imgur":        r"(imgur\.com)",
    "generic":      r".*",
}

BLOCKED_DOMAINS = [
    "malware", "phishing", "localhost", "127.0.0.1", "0.0.0.0",
    "192.168.", "10.", "172.16.", "169.254."
]

# ─── Models ──────────────────────────────────────────────────────────────────
class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"       # best | 1080p | 720p | 480p | 360p | audio_only
    format: str = "auto"        # auto | mp4 | mp3 | jpg | png | webm
    playlist: bool = False
    subtitles: bool = False

    @field_validator("url")
    def validate_url(cls, v):
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL http:// yoki https:// bilan boshlanishi kerak")
        for blocked in BLOCKED_DOMAINS:
            if blocked in v.lower():
                raise ValueError(f"Bu URL ruxsat etilmagan: {blocked}")
        return v

class DownloadStatus(BaseModel):
    task_id: str
    status: str
    progress: float = 0
    message: str = ""
    filename: str = ""
    filesize: int = 0
    platform: str = ""
    media_type: str = ""
    download_url: str = ""
    error: str = ""
    metadata: dict = {}

# ─── Task Storage (in-memory) ─────────────────────────────────────────────────
tasks: dict[str, dict] = {}

# ─── Rate Limiting (simple) ───────────────────────────────────────────────────
rate_limit_store: dict[str, list] = {}
MAX_REQUESTS_PER_MINUTE = 10

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    if ip not in rate_limit_store:
        rate_limit_store[ip] = []
    rate_limit_store[ip] = [t for t in rate_limit_store[ip] if now - t < 60]
    if len(rate_limit_store[ip]) >= MAX_REQUESTS_PER_MINUTE:
        return False
    rate_limit_store[ip].append(now)
    return True

# ─── Platform Detection ───────────────────────────────────────────────────────
def detect_platform(url: str) -> str:
    url_lower = url.lower()
    for platform, pattern in PLATFORM_PATTERNS.items():
        if re.search(pattern, url_lower):
            return platform
    return "generic"

def detect_media_type(url: str, platform: str) -> str:
    url_lower = url.lower()
    
    # Image patterns
    if any(ext in url_lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"]):
        return "image"
    
    # Audio patterns
    if any(ext in url_lower for ext in [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"]):
        return "audio"
    
    # Platform-specific detection
    if platform == "soundcloud":
        return "audio"
    if platform in ["instagram", "pinterest", "flickr", "imgur", "tenor", "giphy"]:
        if "/p/" in url_lower or "/reel/" not in url_lower:
            return "image_or_video"
    if "reel" in url_lower or "reels" in url_lower:
        return "reel"
    if "story" in url_lower or "stories" in url_lower:
        return "story"
    if "shorts" in url_lower:
        return "short"
    if "clip" in url_lower or "clips" in url_lower:
        return "clip"
    if platform == "youtube":
        if "playlist" in url_lower or "list=" in url_lower:
            return "playlist"
        return "video"
    
    return "video"

# ─── Quality Mapping ──────────────────────────────────────────────────────────
def get_format_string(quality: str, fmt: str) -> str:
    """Convert quality/format request to yt-dlp format string"""
    
    if fmt in ["mp3", "audio_only"] or quality == "audio_only":
        return "bestaudio/best"
    
    quality_map = {
        "best":   "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "2160p":  "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]",
        "1080p":  "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
        "720p":   "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
        "480p":   "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
        "360p":   "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
    }
    return quality_map.get(quality, quality_map["best"])

# ─── Downloader Engines ───────────────────────────────────────────────────────
async def download_with_ytdlp(url: str, task_id: str, quality: str, fmt: str, 
                               subtitles: bool = False) -> dict:
    """Primary downloader using yt-dlp - supports 1000+ sites"""
    
    output_path = DOWNLOAD_DIR / task_id
    output_path.mkdir(exist_ok=True)
    
    format_str = get_format_string(quality, fmt)
    
    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = (downloaded / total) * 100
                tasks[task_id]["progress"] = round(pct, 1)
                tasks[task_id]["message"] = f"Yuklanmoqda... {pct:.1f}%"
        elif d["status"] == "finished":
            tasks[task_id]["progress"] = 95
            tasks[task_id]["message"] = "Qayta ishlanmoqda..."
    
    ydl_opts = {
        "format": format_str,
        "outtmpl": str(output_path / "%(title)s.%(ext)s"),
        "progress_hooks": [progress_hook],
        "noplaylist": True,
        "extract_flat": False,
        "ignoreerrors": False,
        "no_warnings": False,
        "cookiesfrombrowser": None,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "writeinfojson": False,
        "writethumbnail": False,
        "geo_bypass": True,
        "age_limit": None,
    }
    
    # Format-specific options
    if fmt == "mp3" or quality == "audio_only":
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }]
    elif fmt == "mp4":
        ydl_opts["merge_output_format"] = "mp4"
    
    if subtitles:
        ydl_opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["uz", "ru", "en"],
        })
    
    loop = asyncio.get_event_loop()
    
    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info
    
    info = await loop.run_in_executor(None, _download)
    
    # Find downloaded file
    files = list(output_path.glob("*"))
    files = [f for f in files if f.is_file() and not f.name.endswith(".json")]
    
    if not files:
        raise Exception("Fayl yuklanmadi")
    
    main_file = max(files, key=lambda f: f.stat().st_size)
    
    metadata = {
        "title": info.get("title", ""),
        "description": (info.get("description") or "")[:200],
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration", 0),
        "view_count": info.get("view_count", 0),
        "like_count": info.get("like_count", 0),
        "upload_date": info.get("upload_date", ""),
        "thumbnail": info.get("thumbnail", ""),
        "extractor": info.get("extractor", ""),
        "width": info.get("width", 0),
        "height": info.get("height", 0),
        "fps": info.get("fps", 0),
        "vcodec": info.get("vcodec", ""),
        "acodec": info.get("acodec", ""),
    }
    
    return {
        "filepath": str(main_file),
        "filename": main_file.name,
        "filesize": main_file.stat().st_size,
        "metadata": metadata,
        "engine": "yt-dlp",
    }

async def download_with_gallery_dl(url: str, task_id: str) -> dict:
    """Fallback: gallery-dl for image-heavy platforms (Instagram, Pinterest, etc.)"""
    import gallery_dl
    from gallery_dl import config, job
    
    output_path = DOWNLOAD_DIR / task_id
    output_path.mkdir(exist_ok=True)
    
    gallery_dl.config.clear()
    gallery_dl.config.set(("extractor",), "base-directory", str(output_path))
    gallery_dl.config.set(("extractor",), "directory", [])
    
    loop = asyncio.get_event_loop()
    
    def _download():
        j = gallery_dl.job.DownloadJob(url)
        j.run()
    
    await loop.run_in_executor(None, _download)
    
    files = list(output_path.rglob("*"))
    files = [f for f in files if f.is_file()]
    
    if not files:
        raise Exception("gallery-dl: fayl yuklanmadi")
    
    if len(files) == 1:
        main_file = files[0]
        return {
            "filepath": str(main_file),
            "filename": main_file.name,
            "filesize": main_file.stat().st_size,
            "metadata": {"files_count": 1},
            "engine": "gallery-dl",
        }
    else:
        # Multiple files (album/gallery) - create info
        total_size = sum(f.stat().st_size for f in files)
        return {
            "filepath": str(output_path),
            "filename": f"{len(files)}_ta_fayl",
            "filesize": total_size,
            "metadata": {"files_count": len(files), "files": [f.name for f in files[:10]]},
            "engine": "gallery-dl",
            "multiple_files": [str(f) for f in files],
        }

async def download_direct(url: str, task_id: str) -> dict:
    """Last resort: direct HTTP download for direct media links"""
    
    output_path = DOWNLOAD_DIR / task_id
    output_path.mkdir(exist_ok=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=300)) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}: Yuklab bo'lmadi")
            
            # Detect filename
            content_disp = resp.headers.get("Content-Disposition", "")
            if "filename=" in content_disp:
                fname = content_disp.split("filename=")[-1].strip('"').strip("'")
            else:
                parsed = urlparse(url)
                fname = Path(parsed.path).name or f"media_{task_id[:8]}"
                if "." not in fname:
                    ctype = resp.headers.get("Content-Type", "")
                    ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ".bin"
                    fname += ext
            
            filepath = output_path / fname
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            
            async with aiofiles.open(filepath, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    await f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = (downloaded / total) * 100
                        tasks[task_id]["progress"] = round(pct, 1)
            
            return {
                "filepath": str(filepath),
                "filename": fname,
                "filesize": filepath.stat().st_size,
                "metadata": {"content_type": resp.headers.get("Content-Type", "")},
                "engine": "direct-http",
            }

# ─── Smart Download Orchestrator ──────────────────────────────────────────────
async def smart_download(task_id: str, url: str, quality: str, fmt: str,
                          subtitles: bool, platform: str):
    """
    Tries multiple engines in order:
    1. yt-dlp (primary - 1000+ sites)
    2. gallery-dl (images/galleries)
    3. Direct HTTP (direct links)
    """
    
    tasks[task_id].update({
        "status": "downloading",
        "message": f"Yuklanmoqda ({platform})...",
        "progress": 5,
    })
    
    engines = [
        ("yt-dlp", lambda: download_with_ytdlp(url, task_id, quality, fmt, subtitles)),
        ("gallery-dl", lambda: download_with_gallery_dl(url, task_id)),
        ("direct-http", lambda: download_direct(url, task_id)),
    ]
    
    last_error = None
    tried_engines = []
    
    for engine_name, engine_func in engines:
        try:
            tasks[task_id]["message"] = f"🔄 {engine_name} orqali yuklanmoqda..."
            logger.info(f"[{task_id}] Trying engine: {engine_name} for {url}")
            
            result = await engine_func()
            
            # Verify file exists and has content
            if "multiple_files" not in result:
                fpath = Path(result["filepath"])
                if not fpath.exists() or fpath.stat().st_size == 0:
                    raise Exception("Bo'sh fayl yoki fayl topilmadi")
                
                # Check file size limit
                size_mb = fpath.stat().st_size / (1024 * 1024)
                if size_mb > MAX_FILE_SIZE_MB:
                    raise Exception(f"Fayl juda katta: {size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB)")
            
            # Success!
            tried_engines.append({"engine": engine_name, "status": "success"})
            
            tasks[task_id].update({
                "status": "completed",
                "progress": 100,
                "message": "✅ Muvaffaqiyatli yuklandi!",
                "filename": result["filename"],
                "filesize": result["filesize"],
                "download_url": f"/download/{task_id}/{result['filename']}",
                "metadata": result.get("metadata", {}),
                "engine_used": engine_name,
                "tried_engines": tried_engines,
                "multiple_files": result.get("multiple_files"),
                "completed_at": datetime.now().isoformat(),
            })
            
            logger.info(f"[{task_id}] Success with {engine_name}: {result['filename']}")
            return
            
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"[{task_id}] {engine_name} failed: {error_msg}")
            tried_engines.append({"engine": engine_name, "status": "failed", "error": error_msg})
            last_error = error_msg
            
            # Don't try gallery-dl for non-image platforms
            if engine_name == "yt-dlp" and platform in ["youtube", "twitch", "vimeo", "dailymotion"]:
                logger.info(f"[{task_id}] Skipping gallery-dl for {platform}")
                engines = [e for e in engines if e[0] != "gallery-dl"]
            
            continue
    
    # All engines failed
    tasks[task_id].update({
        "status": "failed",
        "progress": 0,
        "message": "❌ Barcha yuklovchilar muvaffaqiyatsiz tugadi",
        "error": last_error or "Noma'lum xato",
        "tried_engines": tried_engines,
    })
    logger.error(f"[{task_id}] All engines failed for {url}")

# ─── Lifespan Handler ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(cleanup_old_files())
    logger.info("🚀 Universal Media Downloader ishga tushdi!")
    yield

# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Universal Media Downloader",
    description="YouTube, Instagram, TikTok, Twitter va 1000+ saytdan media yuklovchi",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    root_path="/downloader",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ─── API Routes ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = BASE_DIR / "index.html"
    if html_path.exists():
        async with aiofiles.open(html_path, "r") as f:
            return await f.read()
    return HTMLResponse("<h1>MediaLoader API - /api/docs</h1>")

@app.post("/api/analyze")
async def analyze_url(request: Request, body: DownloadRequest):
    """Analyze URL and return available formats/qualities before downloading"""
    client_ip = request.client.host
    
    if not check_rate_limit(client_ip):
        raise HTTPException(429, "Juda ko'p so'rov. Iltimos kuting.")
    
    platform = detect_platform(body.url)
    media_type = detect_media_type(body.url, platform)
    
    try:
        loop = asyncio.get_event_loop()
        
        def _extract_info():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "socket_timeout": 15,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(body.url, download=False)
        
        info = await asyncio.wait_for(
            loop.run_in_executor(None, _extract_info),
            timeout=20
        )
        
        formats = []
        seen_heights = set()
        
        if info.get("formats"):
            for f in info["formats"]:
                height = f.get("height")
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")
                
                if height and vcodec != "none" and height not in seen_heights:
                    seen_heights.add(height)
                    formats.append({
                        "quality": f"{height}p",
                        "ext": f.get("ext", "mp4"),
                        "filesize": f.get("filesize") or f.get("filesize_approx"),
                        "vcodec": vcodec,
                        "fps": f.get("fps"),
                    })
        
        formats.sort(key=lambda x: int(x["quality"].replace("p", "")), reverse=True)
        
        # Always add audio-only option
        formats.append({"quality": "audio_only", "ext": "mp3", "filesize": None})
        
        return {
            "platform": platform,
            "media_type": media_type,
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", ""),
            "description": (info.get("description") or "")[:300],
            "formats": formats,
            "is_playlist": info.get("_type") == "playlist",
        }
        
    except asyncio.TimeoutError:
        return {
            "platform": platform,
            "media_type": media_type,
            "title": "",
            "formats": [
                {"quality": "best", "ext": "mp4"},
                {"quality": "1080p", "ext": "mp4"},
                {"quality": "720p", "ext": "mp4"},
                {"quality": "480p", "ext": "mp4"},
                {"quality": "360p", "ext": "mp4"},
                {"quality": "audio_only", "ext": "mp3"},
            ],
            "warning": "Tezkor tahlil amalga oshmadi, standart sifatlar ko'rsatilmoqda",
        }
    except Exception as e:
        return {
            "platform": platform,
            "media_type": media_type,
            "formats": [
                {"quality": "best", "ext": "mp4"},
                {"quality": "1080p", "ext": "mp4"},
                {"quality": "720p", "ext": "mp4"},
                {"quality": "audio_only", "ext": "mp3"},
            ],
            "warning": f"Tahlil xatosi: {str(e)[:100]}",
        }

@app.post("/api/download")
async def start_download(request: Request, body: DownloadRequest, background_tasks: BackgroundTasks):
    """Start a download task"""
    client_ip = request.client.host
    
    if not check_rate_limit(client_ip):
        raise HTTPException(429, "Juda ko'p so'rov. 1 daqiqa kuting.")
    
    task_id = str(uuid.uuid4())
    platform = detect_platform(body.url)
    media_type = detect_media_type(body.url, platform)
    
    tasks[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "Navbatda...",
        "url": body.url,
        "platform": platform,
        "media_type": media_type,
        "quality": body.quality,
        "format": body.format,
        "filename": "",
        "filesize": 0,
        "download_url": "",
        "error": "",
        "metadata": {},
        "tried_engines": [],
        "created_at": datetime.now().isoformat(),
        "ip": client_ip,
    }
    
    background_tasks.add_task(
        smart_download,
        task_id, body.url, body.quality, body.format, body.subtitles, platform
    )
    
    logger.info(f"[{task_id}] New task: {platform} | {media_type} | {body.url[:60]}")
    
    return {"task_id": task_id, "platform": platform, "media_type": media_type}

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """Get download task status"""
    if task_id not in tasks:
        raise HTTPException(404, "Vazifa topilmadi")
    
    task = tasks[task_id].copy()
    task.pop("ip", None)  # Don't expose IP
    return task

@app.get("/download/{task_id}/{filename}")
async def download_file(task_id: str, filename: str):
    """Serve downloaded file"""
    if task_id not in tasks:
        raise HTTPException(404, "Vazifa topilmadi")
    
    task = tasks[task_id]
    if task["status"] != "completed":
        raise HTTPException(400, "Fayl hali tayyor emas")
    
    file_path = DOWNLOAD_DIR / task_id / filename
    
    if not file_path.exists():
        # Try to find the file
        files = list((DOWNLOAD_DIR / task_id).glob("*"))
        if files:
            file_path = files[0]
        else:
            raise HTTPException(404, "Fayl topilmadi yoki o'chirilgan")
    
    # Security check - prevent path traversal
    try:
        file_path.resolve().relative_to(DOWNLOAD_DIR.resolve())
    except ValueError:
        raise HTTPException(403, "Ruxsat yo'q")
    
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/octet-stream",
    )

@app.get("/api/tasks")
async def list_tasks(request: Request):
    """List recent tasks (for admin/debug)"""
    result = []
    for tid, t in list(tasks.items())[-20:]:
        result.append({
            "task_id": tid,
            "status": t["status"],
            "platform": t.get("platform"),
            "filename": t.get("filename"),
            "created_at": t.get("created_at"),
        })
    return {"tasks": result, "total": len(tasks)}

@app.delete("/api/task/{task_id}")
async def delete_task(task_id: str):
    """Delete a task and its files"""
    if task_id not in tasks:
        raise HTTPException(404, "Topilmadi")
    
    # Clean up files
    task_dir = DOWNLOAD_DIR / task_id
    if task_dir.exists():
        import shutil
        shutil.rmtree(task_dir, ignore_errors=True)
    
    del tasks[task_id]
    return {"message": "O'chirildi"}

@app.get("/api/supported-sites")
async def supported_sites():
    """Return list of known supported platforms"""
    return {
        "platforms": list(PLATFORM_PATTERNS.keys())[:-1],  # exclude 'generic'
        "note": "yt-dlp orqali 1000+ sayt qo'llab-quvvatlanadi",
        "popular": ["YouTube", "Instagram", "TikTok", "Twitter/X", "Facebook",
                    "Reddit", "SoundCloud", "Vimeo", "Twitch", "Dailymotion",
                    "Pinterest", "Bilibili", "VK", "Telegram", "Streamable"],
    }

@app.get("/api/health")
async def health():
    """Health check"""
    import shutil
    disk = shutil.disk_usage(str(DOWNLOAD_DIR))
    return {
        "status": "ok",
        "active_tasks": len([t for t in tasks.values() if t["status"] in ["queued", "downloading"]]),
        "total_tasks": len(tasks),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "ytdlp_version": yt_dlp.version.__version__,
    }

# ─── Cleanup Background Task ──────────────────────────────────────────────────
async def cleanup_old_files():
    """Periodically remove old downloaded files"""
    while True:
        await asyncio.sleep(3600)  # Every hour
        cutoff = datetime.now() - timedelta(hours=MAX_FILE_AGE_HOURS)
        cleaned = 0
        
        for task_id, task in list(tasks.items()):
            created = datetime.fromisoformat(task.get("created_at", datetime.now().isoformat()))
            if created < cutoff and task["status"] in ["completed", "failed"]:
                task_dir = DOWNLOAD_DIR / task_id
                if task_dir.exists():
                    import shutil
                    shutil.rmtree(task_dir, ignore_errors=True)
                    cleaned += 1
                del tasks[task_id]
        
        if cleaned:
            logger.info(f"Cleanup: {cleaned} eski vazifa va fayl o'chirildi")

@app.post("/api/clean-storage")
async def clean_storage():
    import shutil
    cleaned_files = 0
    cleaned_size = 0

    for task_dir in DOWNLOAD_DIR.iterdir():
        if task_dir.is_dir():
            for file in task_dir.iterdir():
                if file.is_file():
                    cleaned_size += file.stat().st_size
                    cleaned_files += 1
            shutil.rmtree(task_dir, ignore_errors=True)

    tasks.clear()

    return {
        "message": "✅ Yuklanmalar papkasi tozalandi",
        "cleaned_files": cleaned_files,
        "freed_space": f"{cleaned_size / (1024**2):.1f} MB"
    }

@app.on_event("startup")
async def startup():
    asyncio.create_task(cleanup_old_files())
    logger.info("🚀 Universal Media Downloader ishga tushdi!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
