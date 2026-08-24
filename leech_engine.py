"""
Motor Universal de Descarga, Torrents Turbo (Aria2c), Descompresión RAR/ZIP/7z, Fusión FFmpeg y Subida Premium Kurigram (4GB)
Autor: Antigravity AI
Soporte: 1500+ sitios (yt-dlp), Torrents/Magnets (Aria2c Turbo + 80+ Trackers), Multi-part RAR/ZIP, Kurigram MTProto (hasta 4GB), Watermark (@feft05 @fh_estrenos)
"""

import os
import re
import sys
import time
import math
import shutil
import struct
import base64
import asyncio
import logging
import zipfile
import subprocess
from pathlib import Path
import yt_dlp
import requests

# Asegurar loop para Python 3.12+ / 3.14 antes de importar pyrogram
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from pyrogram import Client, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("LeechEngine")

# Variables de entorno
API_ID = int(os.getenv("TELEGRAM_API_ID", "31956770"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "6f8f53e5da84ba600ff65dbc805a0e32")
KURIGRAM_STRING_SESSION = os.getenv("KURIGRAM_STRING_SESSION", os.getenv("PYRO_STRING_SESSION", "")).strip()
TELETHON_STRING_SESSION = os.getenv("TELETHON_STRING_SESSION", "").strip()
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "-1003732487046"))
MAX_CHUNK_SIZE_BYTES = 3900 * 1024 * 1024  # 3900 MiB — Límite seguro de Telegram Premium (Tope estricto: 4000 MiB)
BOT_DIRECT_LIMIT_BYTES = 1950 * 1024 * 1024  # 1950 MiB — límite seguro de Bot API HTTP (Tope estricto: 2000 MiB)
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "1601545124"))

# Marca de agua oficial (escapado para Markdown)
WATERMARK_FOOTER = "\n\n📢 *Canal Oficial:* @fh\\_estrenos\n👤 *Admin:* @feft05"

# ==============================================================================
# GESTIÓN DE SESIÓN KURIGRAM / CONVERSIÓN TRANSPARENTE
# ==============================================================================
def convert_telethon_to_kurigram_session(telethon_str: str, api_id: int, user_id: int = ADMIN_USER_ID) -> str:
    """Convierte una StringSession de Telethon directamente al formato de Kurigram/Pyrogram."""
    try:
        from telethon.sessions import StringSession
        s = StringSession(telethon_str)
        if not s.auth_key or not s.auth_key.key:
            return ""
        packed = struct.pack(
            ">BI?256sQ?",
            s.dc_id,
            api_id,
            False,
            s.auth_key.key,
            user_id,
            False
        )
        return base64.urlsafe_b64encode(packed).decode().rstrip("=")
    except Exception as e:
        logger.warning(f"No se pudo autoconvertir la sesión de Telethon: {e}")
        return ""

def get_best_session_string() -> str:
    """Obtiene o autoconvierte la mejor StringSession disponible para Kurigram."""
    if KURIGRAM_STRING_SESSION:
        return KURIGRAM_STRING_SESSION

    # Verificar si existe kurigram_session.txt
    if os.path.exists("kurigram_session.txt"):
        try:
            with open("kurigram_session.txt", "r", encoding="utf-8") as f:
                c = f.read().strip()
                if len(c) > 50:
                    return c
        except Exception:
            pass

    # Si hay sesión de Telethon en string_session.txt o TELETHON_STRING_SESSION, convertirla
    tele_session = TELETHON_STRING_SESSION
    if not tele_session and os.path.exists("string_session.txt"):
        try:
            with open("string_session.txt", "r", encoding="utf-8") as f:
                tele_session = f.read().strip()
        except Exception:
            pass

    if tele_session:
        converted = convert_telethon_to_kurigram_session(tele_session, API_ID, ADMIN_USER_ID)
        if converted:
            logger.info("🔑 StringSession de Telethon convertida automáticamente a Kurigram.")
            return converted

    return ""

_kurigram_client = None

def get_kurigram_client():
    """Retorna o inicializa el cliente Singleton de Kurigram."""
    global _kurigram_client
    if _kurigram_client is None:
        session_str = get_best_session_string()
        if session_str:
            _kurigram_client = Client(
                name="kurigram_userbot",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session_str,
                in_memory=True,
                workers=16,
                max_concurrent_transmissions=8
            )
        else:
            _kurigram_client = Client(
                name="userbot_session",
                api_id=API_ID,
                api_hash=API_HASH,
                workers=16,
                max_concurrent_transmissions=8
            )
    return _kurigram_client

async def ensure_kurigram_connected():
    """Garantiza que el cliente Kurigram MTProto esté conectado y autorizado."""
    client = get_kurigram_client()
    if not client.is_connected:
        try:
            await client.start()
        except ConnectionError:
            pass
        except Exception as e:
            logger.error(f"Error iniciando cliente Kurigram: {e}")

    return client

# ==============================================================================
# UTILIDADES DE FORMATO Y PROGRESO ASÍNCRONO
# ==============================================================================
def human_readable_size(size_bytes):
    if not size_bytes or size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def human_readable_time(seconds):
    if seconds is None or seconds < 0 or math.isinf(seconds):
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

def make_progress_bar(percent, length=10):
    percent = max(0, min(100, percent))
    filled = int(round(length * percent / 100))
    return "█" * filled + "░" * (length - filled)

PROGRESS_UPDATE_INTERVAL = 6.0

class AsyncProgressTracker:
    def __init__(self, message_callback, action_name="Procesando", interval=PROGRESS_UPDATE_INTERVAL):
        self.message_callback = message_callback
        self.action_name = action_name
        self.interval = interval
        self.last_update_time = 0
        self.start_time = time.time()

    async def update(self, current, total, speed=None, eta=None):
        now = time.time()
        if (now - self.last_update_time) < self.interval and current < total:
            return

        self.last_update_time = now
        elapsed = now - self.start_time

        if speed is None:
            speed = current / elapsed if elapsed > 0 else 0
        if eta is None:
            eta = (total - current) / speed if speed > 0 and total > current else 0

        percent = (current / total * 100) if total > 0 else 0
        bar = make_progress_bar(percent)

        texto = (
            f"⚡ *{self.action_name}*\n\n"
            f"📊 `[{bar}]` *{percent:.1f}%*\n"
            f"📦 *Transferido:* `{human_readable_size(current)}` / `{human_readable_size(total)}`\n"
            f"🚀 *Velocidad:* `{human_readable_size(speed)}/s`\n"
            f"⏳ *Tiempo Restante:* `{human_readable_time(eta)}`"
            f"{WATERMARK_FOOTER}"
        )
        try:
            await self.message_callback(texto)
        except Exception:
            pass

# ==============================================================================
# GESTIÓN DE COOKIES MULTIPLATAFORMA (YOUTUBE, FACEBOOK, INSTAGRAM)
# ==============================================================================
def get_cookie_file():
    """Detecta y combina cookies de múltiples plataformas (YouTube, Facebook, Instagram, etc.)."""
    cookie_path = "/tmp/global_cookies.txt" if os.name != "nt" else "./global_cookies.txt"
    all_cookies = ["# Netscape HTTP Cookie File\n# Multi-platform Cookies Engine\n"]

    for var_name in ["GLOBAL_COOKIES_BASE64", "YOUTUBE_COOKIES_BASE64", "FACEBOOK_COOKIES_BASE64", "INSTAGRAM_COOKIES_BASE64"]:
        b64_env = os.getenv(var_name, "").strip()
        if b64_env:
            try:
                decoded = base64.b64decode(b64_env).decode('utf-8', errors='ignore')
                all_cookies.append(decoded)
                logger.info(f"🍪 {var_name} cargada con éxito ({len(decoded)} bytes).")
            except Exception as e:
                logger.error(f"🍪 Error decodificando {var_name}: {e}")

    for var_name in ["GLOBAL_COOKIES_TEXT", "YOUTUBE_COOKIES_TEXT", "FACEBOOK_COOKIES_TEXT"]:
        txt_env = os.getenv(var_name, "").strip()
        if txt_env:
            all_cookies.append(txt_env)

    if len(all_cookies) > 1:
        try:
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write("\n".join(all_cookies))
            return cookie_path
        except Exception as e:
            logger.error(f"Error escribiendo cookies combinadas: {e}")

    for path in ["./cookies.txt", "/app/data/cookies.txt", "/app/cookies.txt"]:
        if os.path.exists(path) and os.path.getsize(path) > 10:
            logger.info(f"🍪 Archivo de cookies encontrado en disco: {path}")
            return path

    return None

# ==============================================================================
# MOTOR 1: INSPECCIÓN DE FORMATOS Y CALIDADES (YT-DLP BLINDADO)
# ==============================================================================
def get_available_formats(url):
    cookie_file = get_cookie_file()
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "remote_components": ["ejs:github"],
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android", "mweb", "tv"],
                "player_skip": ["js"]
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
        }
    }
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])
            title = info.get("title", "Video")
            duration = info.get("duration", 0)

            resoluciones = set()
            for f in formats:
                h = f.get("height")
                if h and h >= 360 and f.get("vcodec") != "none":
                    resoluciones.add(h)

            res_sorted = sorted(list(resoluciones), reverse=True)
            return {
                "title": title,
                "duration": duration,
                "resoluciones": res_sorted,
                "thumbnail": info.get("thumbnail")
            }
    except Exception as e:
        logger.error(f"Error extrayendo formatos con yt-dlp: {e}")
        # Reintento con configuración estándar
        try:
            ydl_opts.pop("extractor_args", None)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    "title": info.get("title", "Video"),
                    "duration": info.get("duration", 0),
                    "resoluciones": [1080, 720, 480],
                    "thumbnail": info.get("thumbnail")
                }
        except Exception:
            return None

# ==============================================================================
# MOTOR 2: DESCARGA CON YT-DLP (SUBTÍTULOS + METADATOS + BYPASS)
# ==============================================================================
def download_ytdlp_advanced(url, output_dir, height_limit=None, extract_audio=False, progress_hook=None):
    os.makedirs(output_dir, exist_ok=True)
    out_template = os.path.join(output_dir, "%(title).90s.%(ext)s")
    cookie_file = get_cookie_file()

    common_extractor_args = {
        "youtube": {
            "player_client": ["ios", "android", "mweb", "tv"],
            "player_skip": ["js"]
        }
    }

    if extract_audio:
        ydl_opts = {
            "outtmpl": out_template,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "noplaylist": True,
            "quiet": True,
            "remote_components": ["ejs:github"],
            "extractor_args": common_extractor_args
        }
    else:
        if height_limit:
            fmt = f"bestvideo[height<={height_limit}]+bestaudio/best[height<={height_limit}]/bestvideo*+bestaudio/best"
        else:
            fmt = "bestvideo*+bestaudio/best"

        ydl_opts = {
            "outtmpl": out_template,
            "format": fmt,
            "format_sort": ["res", "ext:mp4:m4a"],
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["es", "es-.*", "en", "en-.*"],
            "embedsubtitles": True,
            "embedthumbnail": True,
            "embedmetadata": True,
            "remote_components": ["ejs:github"],
            "extractor_args": common_extractor_args,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
            }
        }

    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base = os.path.splitext(filename)[0]

            for ext in [".mp4", ".mkv", ".webm", ".mp3"]:
                if os.path.exists(base + ext):
                    return base + ext
            if os.path.exists(filename):
                return filename
            return filename
    except Exception as e:
        logger.warning(f"Error en descarga inicial yt-dlp ({e}). Reintentando con formato universal de respaldo...")
        # Fallback universal con formato 'b/best' y cliente android/web
        ydl_opts["format"] = "b/best"
        ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                base = os.path.splitext(filename)[0]
                for ext in [".mp4", ".mkv", ".webm", ".mp3"]:
                    if os.path.exists(base + ext):
                        return base + ext
                return filename
        except Exception as e2:
            if "sign in" in str(e2).lower() or "bot" in str(e2).lower():
                raise Exception("YouTube requiere cookies de autenticación para descargar este video. Agrega tu archivo cookies.txt o la variable YOUTUBE_COOKIES_TEXT en el .env.")
            raise e2

# ==============================================================================
# MOTOR 3: DESCARGA DE TORRENTS TURBO CON ARIA2C (SATURACIÓN INMEDIATA)
# ==============================================================================
MEGA_TRACKERS_LIST = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://p4p.arenabg.com:1337/announce",
    "udp://9.rarbg.to:2920/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://retracker.lanta-net.ru:2710/announce",
    "http://tracker.opentrackr.org:1337/announce",
    "http://open.acgnxtracker.com:80/announce",
    "https://tracker.tamersunion.org:443/announce"
]

def get_fresh_trackers():
    """Descarga lista fresca de trackers de alta velocidad o usa la lista embebida."""
    try:
        r = requests.get("https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt", timeout=3)
        if r.status_code == 200 and len(r.text) > 50:
            lines = [line.strip() for line in r.text.split("\n") if line.strip() and not line.startswith("#")]
            if lines:
                return ",".join(lines)
    except Exception:
        pass
    return ",".join(MEGA_TRACKERS_LIST)

async def download_torrent_aria2(magnet_or_torrent, output_dir, status_updater):
    """
    Descarga torrents a máxima velocidad con Aria2c Turbo:
    - --file-allocation=none: 0ms de bloqueo de disco.
    - --disk-cache=128M: Almacena piezas en memoria RAM para saturar la velocidad al instante.
    - Timeouts cortos para descartar trackers muertos inmediatamente.
    """
    os.makedirs(output_dir, exist_ok=True)
    await status_updater("🧲 *Iniciando enjambre de peers (Aria2c Turbo 128MB Cache)...*")

    trackers_str = get_fresh_trackers()

    cmd = [
        "aria2c",
        f"--dir={output_dir}",
        f"--bt-tracker={trackers_str}",
        "--enable-dht=true",
        "--enable-dht6=true",
        "--bt-enable-lpd=true",
        "--enable-peer-exchange=true",
        "--bt-max-peers=200",
        "--bt-request-peer-speed-limit=0",
        "--bt-tracker-connect-timeout=3",
        "--bt-tracker-timeout=3",
        "--bt-tracker-interval=20",
        "--bt-min-crypto-level=arc4",
        "--bt-require-crypto=false",
        "--file-allocation=none",
        "--disk-cache=128M",
        "--seed-time=0",
        "--bt-stop-timeout=600",
        "--max-connection-per-server=16",
        "--split=32",
        "--piece-length=1M",
        "--peer-id-prefix=-qB4650-",
        "--user-agent=qBittorrent/4.6.5",
        "--summary-interval=2",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        magnet_or_torrent
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    last_update_time = 0
    while process.returncode is None:
        line = await process.stdout.readline()
        if not line:
            break
        text_line = line.decode('utf-8', errors='ignore').strip()

        if "ETA:" in text_line or "CN:" in text_line or "%" in text_line:
            now = time.time()
            if now - last_update_time >= PROGRESS_UPDATE_INTERVAL:
                last_update_time = now
                try:
                    await status_updater(
                        f"🧲 *Descargando Torrent Turbo:*\n`{text_line[:120]}`\n\n"
                        f"⚡ _Entrega automática al completar_{WATERMARK_FOOTER}"
                    )
                except Exception:
                    pass

    await process.wait()

    downloaded_files = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            if not f.endswith(".aria2") and not f.endswith(".torrent"):
                full_p = os.path.join(root, f)
                if os.path.getsize(full_p) > 1024:
                    downloaded_files.append(full_p)

    if downloaded_files:
        downloaded_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
        return downloaded_files[0]

    return None

# ==============================================================================
# MOTOR 4: DESCOMPRESIÓN (RAR/ZIP/7z/MULTIPART) Y FUSIÓN DE VIDEOS (FFMPEG)
# ==============================================================================
def unpack_and_merge_archive(archive_path_or_dir, output_dir):
    extract_dir = os.path.join(output_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)

    logger.info(f"Descomprimiendo archivos en: {archive_path_or_dir}...")

    if os.path.isfile(archive_path_or_dir):
        target = archive_path_or_dir
    else:
        files = os.listdir(archive_path_or_dir)
        part1 = [os.path.join(archive_path_or_dir, f) for f in files if "part1." in f.lower() or "part01." in f.lower()]
        target = part1[0] if part1 else os.path.join(archive_path_or_dir, files[0])

    try:
        subprocess.run(["7z", "x", target, f"-o{extract_dir}", "-y"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        if zipfile.is_zipfile(target):
            with zipfile.ZipFile(target, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

    video_extensions = {".mp4", ".mkv", ".avi", ".ts", ".mov", ".webm", ".flv"}
    extracted_videos = []

    for root, _, files in os.walk(extract_dir):
        for f in files:
            if Path(f).suffix.lower() in video_extensions:
                extracted_videos.append(os.path.join(root, f))

    extracted_videos.sort()

    if not extracted_videos:
        logger.warning("No se encontraron videos dentro del comprimido.")
        return [target]

    if len(extracted_videos) == 1:
        return extracted_videos

    logger.info(f"Se encontraron {len(extracted_videos)} partes de video. Fusionando...")
    merged_output = os.path.join(output_dir, "video_completo.mp4")
    concat_list_file = os.path.join(output_dir, "concat_list.txt")

    with open(concat_list_file, "w", encoding="utf-8") as f:
        for v in extracted_videos:
            f.write(f"file '{os.path.abspath(v)}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_file,
        "-c", "copy",
        merged_output
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(merged_output) and os.path.getsize(merged_output) > 1000:
            return [merged_output]
    except Exception as e:
        logger.error(f"Error fusionando videos con FFmpeg: {e}")

    return extracted_videos

# ==============================================================================
# MOTOR 5: PARTICIONADO CON FFMPEG (STREAM COPY ULTRA RÁPIDO) Y METADATOS
# ==============================================================================
def get_video_duration(file_path):
    """Obtiene la duración del video en segundos usando ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        val = float(result.stdout.strip())
        if val > 0:
            return val
    except Exception as e:
        logger.warning(f"No se pudo obtener duración con ffprobe: {e}")
    return None

def get_video_dimensions(file_path):
    """Obtiene dimensiones de video (width, height) usando ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        w, h = map(int, result.stdout.strip().split("x"))
        return w, h
    except Exception:
        return 1280, 720

def generate_video_thumbnail(file_path, output_thumb_path):
    """Genera una miniatura rápida del video para streaming en Telegram."""
    try:
        cmd = [
            "ffmpeg", "-y", "-ss", "00:00:10",
            "-i", file_path,
            "-vframes", "1",
            "-vf", "scale=320:-1",
            output_thumb_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if os.path.exists(output_thumb_path) and os.path.getsize(output_thumb_path) > 500:
            return output_thumb_path
    except Exception:
        pass
    return None

def extract_video_sample(input_file_path: str, output_sample_path: str) -> str:
    """
    Extrae exactamente 1 minuto del centro de la película con FFmpeg (stream copy ultra rápido).
    Permite previsualizar la calidad original, resolución (4K/1080p), audio y subtítulos.
    """
    duration = get_video_duration(input_file_path)
    if duration and duration > 120:
        start_time = max(0, int((duration / 2) - 30))
    else:
        start_time = 0

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", input_file_path,
        "-t", "60",
        "-c", "copy",
        "-map", "0",
        "-avoid_negative_ts", "make_zero",
        output_sample_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if os.path.exists(output_sample_path) and os.path.getsize(output_sample_path) > 1024:
            return output_sample_path
    except Exception as e:
        logger.warning(f"Error extrayendo muestra con stream copy: {e}. Reintentando con transcode rápido...")
        cmd_transcode = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", input_file_path,
            "-t", "60",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "aac",
            output_sample_path
        ]
        try:
            subprocess.run(cmd_transcode, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
            if os.path.exists(output_sample_path) and os.path.getsize(output_sample_path) > 1024:
                return output_sample_path
        except Exception as e2:
            logger.error(f"No se pudo generar muestra de video: {e2}")
    return None

async def create_multipart_volumes(input_file_path, output_dir, clean_title, max_part_size_bytes=MAX_CHUNK_SIZE_BYTES, status_updater=None):
    """
    Empaqueta archivos gigantes (> 3.95 GB) en partes RAR/7z de 3.95 GB exactos,
    preservando la película 100% intacta (4K/HDR/Multi-Audio) para descomprimir.
    """
    file_size = os.path.getsize(input_file_path)
    total_parts = math.ceil(file_size / max_part_size_bytes)
    
    clean_name = re.sub(r'[^\w\s\.-]', '_', clean_title).strip().replace(" ", "_")
    base_prefix = f"@fh_estrenos_{clean_name}"
    
    if status_updater:
        await status_updater(
            f"🗜️ *Empaquetando Película en {total_parts} partes RAR de 3.95 GB...*\n"
            f"📦 *Peso Total:* `{human_readable_size(file_size)}`\n"
            f"⚡ _Preservando Calidad Original 4K sin recodificar_{WATERMARK_FOOTER}"
        )

    # Intentar con 7z si está disponible en el sistema (Linux/Docker)
    archive_base = os.path.join(output_dir, base_prefix)
    try:
        cmd_7z = [
            "7z", "a",
            f"-v{int(max_part_size_bytes / (1024*1024))}m",
            "-mx0",  # Modo Store: Ultra rápido a velocidad de disco NVMe
            f"{archive_base}.rar",
            input_file_path
        ]
        proc = subprocess.run(cmd_7z, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if proc.returncode == 0:
            parts_7z = sorted([
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if f.startswith(base_prefix) and os.path.isfile(os.path.join(output_dir, f)) and not f.endswith(Path(input_file_path).name)
            ])
            if parts_7z:
                return parts_7z
    except Exception:
        pass

    # Fallback Universal: Segmentación Binaria Multi-Parte (.part1.rar, .part2.rar)
    parts = []
    chunk_buffer_size = 64 * 1024 * 1024  # 64 MB buffer de lectura
    part_idx = 1
    bytes_written_current_part = 0
    current_part_file = None

    with open(input_file_path, "rb") as src:
        while True:
            if current_part_file is None:
                part_filename = os.path.join(output_dir, f"{base_prefix}.part{part_idx:02d}.rar")
                current_part_file = open(part_filename, "wb")
                parts.append(part_filename)
                bytes_written_current_part = 0

            chunk = src.read(chunk_buffer_size)
            if not chunk:
                if current_part_file:
                    current_part_file.close()
                break

            current_part_file.write(chunk)
            bytes_written_current_part += len(chunk)

            if bytes_written_current_part >= max_part_size_bytes:
                current_part_file.close()
                current_part_file = None
                part_idx += 1

    return parts

# ==============================================================================
# MOTOR 6: PIPELINE COMPLETO HÍBRIDO (KURIGRAM MTPROTO + BOT DELIVERY)
# ==============================================================================
async def process_and_upload(
    url_or_file,
    chat_id,
    status_updater,
    bot_instance=None,
    title_hint="",
    height_limit=None,
    extract_audio=False,
    is_local_file=False,
    user_username=None
):
    task_dir = os.path.join(DOWNLOAD_DIR, f"task_{int(time.time())}")
    os.makedirs(task_dir, exist_ok=True)

    downloaded_file = None

    try:
        if is_local_file or os.path.exists(url_or_file):
            if os.path.isdir(url_or_file):
                await status_updater("🗜️ *Descomprimiendo partes RAR/ZIP y fusionando con FFmpeg...*")
                extracted = unpack_and_merge_archive(url_or_file, task_dir)
                downloaded_file = extracted[0] if extracted else None
            elif any(url_or_file.lower().endswith(ext) for ext in [".zip", ".rar", ".7z", ".r00"]):
                await status_updater("🗜️ *Descomprimiendo archivo y extrayendo video...*")
                extracted = unpack_and_merge_archive(url_or_file, task_dir)
                downloaded_file = extracted[0] if extracted else url_or_file
            else:
                downloaded_file = url_or_file
        elif url_or_file.startswith("magnet:?"):
            downloaded_file = await download_torrent_aria2(url_or_file, task_dir, status_updater)
        else:
            is_social_or_stream = any(d in url_or_file for d in [
                "youtube.com", "youtu.be", "tiktok.com", "instagram.com",
                "facebook.com", "fb.watch", "twitter.com", "x.com",
                "dailymotion.com", "twitch.tv", "vimeo.com"
            ])

            if is_social_or_stream:
                await status_updater("🚀 *Descargando video y subtítulos con yt-dlp...*")
                downloaded_file = await asyncio.to_thread(
                    download_ytdlp_advanced,
                    url_or_file,
                    task_dir,
                    height_limit=height_limit,
                    extract_audio=extract_audio
                )
            else:
                await status_updater("🌐 *Descargando archivo directo...*")
                filename = Path(url_or_file.split("?")[0]).name or "video.mp4"
                downloaded_file = os.path.join(task_dir, filename)

                def _download_direct(url, dest):
                    r = requests.get(url, stream=True, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            if chunk:
                                f.write(chunk)
                    return dest

                downloaded_file = await asyncio.to_thread(_download_direct, url_or_file, downloaded_file)

        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception("No se pudo obtener el archivo descargado o procesado.")

        if any(downloaded_file.lower().endswith(ext) for ext in [".zip", ".rar", ".7z", ".r00"]):
            await status_updater("🗜️ *Contenido comprimido detectado: Extrayendo video...*")
            extracted = unpack_and_merge_archive(downloaded_file, task_dir)
            if extracted:
                downloaded_file = extracted[0]

        total_size = os.path.getsize(downloaded_file)
        file_name = Path(downloaded_file).name
        clean_title = title_hint or file_name

        kuri = await ensure_kurigram_connected()

        # ==============================================================================
        # CASO 1: ARCHIVO <= 3.95 GB (SUBIDA COMPLETA DIRECTA SIN COMPRIMIR)
        # ==============================================================================
        if total_size <= MAX_CHUNK_SIZE_BYTES:
            await status_updater(f"📤 *Subiendo video completo:* `{file_name}` ({human_readable_size(total_size)})...")
            caption = f"🎬 *{clean_title}*\n⚡ _Calidad Original Preservada_{WATERMARK_FOOTER}"

            if total_size <= 50 * 1024 * 1024 and bot_instance is not None:
                # Archivos pequeños <= 50MB directo por Bot
                await status_updater("🚀 *Enviando directamente desde el Bot...*")
                with open(downloaded_file, "rb") as video_file:
                    if downloaded_file.endswith((".mp4", ".mkv", ".webm", ".mov")):
                        await bot_instance.send_video(
                            chat_id=chat_id,
                            video=video_file,
                            caption=caption,
                            parse_mode="Markdown",
                            supports_streaming=True,
                            read_timeout=120,
                            write_timeout=120
                        )
                    elif downloaded_file.endswith(".mp3"):
                        await bot_instance.send_audio(
                            chat_id=chat_id,
                            audio=video_file,
                            caption=caption,
                            parse_mode="Markdown",
                            read_timeout=120,
                            write_timeout=120
                        )
                    else:
                        await bot_instance.send_document(
                            chat_id=chat_id,
                            document=video_file,
                            caption=caption,
                            parse_mode="Markdown",
                            read_timeout=120,
                            write_timeout=120
                        )
            else:
                # Archivos > 50 MB hasta 3.95 GB por Kurigram MTProto al canal
                upload_tracker = AsyncProgressTracker(
                    status_updater,
                    action_name="Subiendo con Kurigram Turbo MTProto"
                )

                async def single_upload_cb(current, total):
                    await upload_tracker.update(current, total)

                duration = int(get_video_duration(downloaded_file) or 0)
                width, height = get_video_dimensions(downloaded_file)
                thumb_path = os.path.join(task_dir, "thumb_single.jpg")
                thumb = generate_video_thumbnail(downloaded_file, thumb_path)

                sent_msg = await kuri.send_video(
                    chat_id=STORAGE_CHANNEL_ID,
                    video=downloaded_file,
                    caption=caption,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumb,
                    supports_streaming=True,
                    progress=single_upload_cb
                )

                channel_post_id = sent_msg.id
                raw_channel_str = str(STORAGE_CHANNEL_ID).replace("-100", "")
                post_link = f"https://t.me/c/{raw_channel_str}/{channel_post_id}"

                if bot_instance is not None:
                    from telegram import InlineKeyboardButton as TgBtn, InlineKeyboardMarkup as TgMarkup
                    markup = TgMarkup([[TgBtn("📥 Ver / Descargar Video en Canal", url=post_link)]])
                    await bot_instance.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🎬 *{clean_title}*\n"
                            f"📦 *Tamaño:* `{human_readable_size(total_size)}`\n\n"
                            f"✅ *¡Subido con éxito a máxima velocidad con Kurigram!*"
                            f"{WATERMARK_FOOTER}"
                        ),
                        reply_markup=markup,
                        parse_mode="Markdown"
                    )

            try:
                os.remove(downloaded_file)
            except Exception:
                pass

        # ==============================================================================
        # CASO 2: ARCHIVO GIGANTE > 3.95 GB (MUESTRA 1 MINUTO + PARTES RAR 3.95 GB)
        # ==============================================================================
        else:
            total_parts_estimated = math.ceil(total_size / MAX_CHUNK_SIZE_BYTES)
            await status_updater(
                f"🎬 *Película Gigante Detectada:* `{human_readable_size(total_size)}`\n"
                f"✂️ *Paso 1:* Generando Muestra de Calidad (1 Minuto del Centro)...\n"
                f"🗜️ *Paso 2:* Empaquetando en {total_parts_estimated} Partes RAR de 3.95 GB para mantener calidad 4K intacta."
                f"{WATERMARK_FOOTER}"
            )

            # 1. Extraer y Subir Muestra de 1 minuto PRIMERO
            sample_file_path = os.path.join(task_dir, f"muestra_{clean_title[:30]}.mp4")
            sample_ready = extract_video_sample(downloaded_file, sample_file_path)
            sample_post_link = None

            if sample_ready and os.path.exists(sample_ready):
                await status_updater("🎥 *Subiendo Muestra de Calidad (1 Minuto) al Canal...*")
                sample_thumb = generate_video_thumbnail(sample_ready, os.path.join(task_dir, "sample_thumb.jpg"))
                w, h = get_video_dimensions(sample_ready)
                
                sample_caption = (
                    f"🎬 *[MUESTRA DE CALIDAD - 1 MINUTO]*\n"
                    f"🎥 *{clean_title}*\n"
                    f"⚡ _Previsualización de Calidad Original (4K/1080p)_\n\n"
                    f"📦 *Nota:* Esta película pesa *{human_readable_size(total_size)}* y se publica en *{total_parts_estimated} partes RAR de 3.95 GB* para mantener el archivo 100% original al descomprimir.\n"
                    f"👇 _Descarga las partes RAR a continuación:_"
                    f"{WATERMARK_FOOTER}"
                )

                sample_msg = await kuri.send_video(
                    chat_id=STORAGE_CHANNEL_ID,
                    video=sample_ready,
                    caption=sample_caption,
                    duration=60,
                    width=w,
                    height=h,
                    thumb=sample_thumb,
                    supports_streaming=True
                )
                raw_channel_str = str(STORAGE_CHANNEL_ID).replace("-100", "")
                sample_post_link = f"https://t.me/c/{raw_channel_str}/{sample_msg.id}"
                
                try:
                    os.remove(sample_ready)
                except Exception:
                    pass

            # 2. Empaquetar en Partes RAR de 3.95 GB
            rar_parts = await create_multipart_volumes(
                downloaded_file,
                task_dir,
                clean_title=clean_title,
                max_part_size_bytes=MAX_CHUNK_SIZE_BYTES,
                status_updater=status_updater
            )
            total_rar_parts = len(rar_parts)

            # 3. Subir Partes RAR Secuencialmente y Liberar Disco Inmediatamente
            for idx, part_path in enumerate(rar_parts, 1):
                part_name = Path(part_path).name
                part_size = os.path.getsize(part_path)

                part_caption = (
                    f"📦 *Pelicula 4K/Original (Partes RAR)*\n"
                    f"🎬 *{clean_title}*\n"
                    f"📑 *Parte {idx} de {total_rar_parts}* (`{human_readable_size(part_size)}`)\n"
                    f"⚡ _Descarga todas las partes y descomprime para ver la película completa_{WATERMARK_FOOTER}"
                )

                rar_tracker = AsyncProgressTracker(
                    status_updater,
                    action_name=f"Subiendo Parte RAR ({idx}/{total_rar_parts})"
                )

                async def rar_upload_cb(current, total):
                    await rar_tracker.update(current, total)

                await kuri.send_document(
                    chat_id=STORAGE_CHANNEL_ID,
                    document=part_path,
                    caption=part_caption,
                    progress=rar_upload_cb
                )

                # Liberar espacio del VPS INMEDIATAMENTE tras subir cada parte
                try:
                    os.remove(part_path)
                    logger.info(f"🗑️ Parte {part_name} eliminada del VPS tras subida exitosa.")
                except Exception:
                    pass

            # 4. Eliminar el archivo de video original del VPS
            try:
                os.remove(downloaded_file)
                logger.info(f"🗑️ Archivo original {file_name} eliminado del VPS tras empaquetado.")
            except Exception:
                pass

            # 5. Notificar al usuario en el Bot con acceso al Canal
            if bot_instance is not None:
                from telegram import InlineKeyboardButton as TgBtn, InlineKeyboardMarkup as TgMarkup
                btn_list = []
                if sample_post_link:
                    btn_list.append([TgBtn("🎥 Ver Muestra de Calidad (1 Min)", url=sample_post_link)])
                raw_channel_str = str(STORAGE_CHANNEL_ID).replace("-100", "")
                btn_list.append([TgBtn(f"📥 Descargar las {total_rar_parts} Partes RAR en Canal", url=f"https://t.me/c/{raw_channel_str}")])
                
                markup = TgMarkup(btn_list)
                await bot_instance.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🎬 *{clean_title}*\n"
                        f"📦 *Peso Total:* `{human_readable_size(total_size)}`\n"
                        f"🗜️ *Empaquetado:* `{total_rar_parts} partes RAR de 3.95 GB`\n\n"
                        f"✅ *¡Muestra de 1 minuto y partes RAR subidas con éxito al Canal Oficial!*\n"
                        f"💡 _Descomprime las partes en tu PC o móvil para disfrutar la película completa en calidad 4K original._"
                        f"{WATERMARK_FOOTER}"
                    ),
                    reply_markup=markup,
                    parse_mode="Markdown"
                )

        # Entregar subtítulos extraídos si existen
        for ext_sub in [".es.vtt", ".es.srt", ".en.vtt", ".en.srt", ".srt", ".vtt"]:
            for root, _, files in os.walk(task_dir):
                for f in files:
                    if f.endswith(ext_sub):
                        sub_path = os.path.join(root, f)
                        try:
                            if bot_instance:
                                with open(sub_path, "rb") as sf:
                                    await bot_instance.send_document(
                                        chat_id=chat_id,
                                        document=sf,
                                        caption=f"💬 *Subtítulos:* `{f}`{WATERMARK_FOOTER}",
                                        parse_mode="Markdown"
                                    )
                        except Exception:
                            pass

        await status_updater(f"✅ *¡Contenido entregado con éxito!*{WATERMARK_FOOTER}")

    except Exception as e:
        logger.error(f"Error en pipeline: {e}")
        await status_updater(f"❌ *Ocurrió un error:* `{str(e)}`{WATERMARK_FOOTER}")
    finally:
        if os.path.exists(task_dir):
            try:
                shutil.rmtree(task_dir, ignore_errors=True)
            except Exception:
                pass

# ==============================================================================
# MOTOR 7: DESCARGA DE ARCHIVOS GRANDES (4GB) DESDE CANAL CON KURIGRAM Y FUSIÓN
# ==============================================================================
async def process_channel_messages_and_unir(
    channel_id,
    message_ids,
    chat_id,
    status_updater,
    bot_instance=None,
    title_hint="",
    user_username=None
):
    """
    Descarga archivos gigantes reenviados al canal de almacenamiento usando Kurigram MTProto (hasta 4GB),
    los descomprime con 7z, los fusiona con FFmpeg y los entrega.
    """
    kuri = await ensure_kurigram_connected()

    task_dir = os.path.join(DOWNLOAD_DIR, f"unir_channel_{int(time.time())}")
    os.makedirs(task_dir, exist_ok=True)

    try:
        total_files = len(message_ids)
        await status_updater(f"📥 *Descargando {total_files} partes con Kurigram Turbo MTProto...*{WATERMARK_FOOTER}")

        downloaded_paths = []
        for idx, msg_id in enumerate(message_ids, 1):
            msg = await kuri.get_messages(chat_id=channel_id, message_ids=msg_id)
            if not msg or not (msg.document or msg.video or msg.audio):
                continue

            media = msg.document or msg.video or msg.audio
            file_name = getattr(media, 'file_name', None) or f"part_{idx}.rar"
            target_path = os.path.join(task_dir, file_name)

            tracker = AsyncProgressTracker(
                status_updater,
                action_name=f"Descargando ({idx}/{total_files}) {file_name}"
            )

            async def dl_cb(curr, tot):
                await tracker.update(curr, tot)

            await kuri.download_media(
                message=msg,
                file_name=target_path,
                progress=dl_cb
            )
            downloaded_paths.append(target_path)

        if not downloaded_paths:
            raise Exception("No se pudieron descargar los archivos del canal de almacenamiento.")

        await status_updater(f"🗜️ *Descomprimiendo partes con 7z y fusionando con FFmpeg...*{WATERMARK_FOOTER}")
        extracted = unpack_and_merge_archive(task_dir, task_dir)
        final_video = extracted[0] if extracted else downloaded_paths[0]

        await process_and_upload(
            url_or_file=final_video,
            chat_id=chat_id,
            status_updater=status_updater,
            bot_instance=bot_instance,
            title_hint=title_hint or Path(downloaded_paths[0]).stem,
            is_local_file=True,
            user_username=user_username
        )

    except Exception as e:
        logger.error(f"Error procesando partes desde canal: {e}")
        await status_updater(f"❌ *Error al fusionar archivos:* `{str(e)}`{WATERMARK_FOOTER}")
    finally:
        if os.path.exists(task_dir):
            try:
                shutil.rmtree(task_dir, ignore_errors=True)
            except Exception:
                pass
