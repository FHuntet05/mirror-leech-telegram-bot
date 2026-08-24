"""
Bot Multimedia Universal + Leech Híbrido (Torrents + RAR/ZIP Fusión + Calidades + Watermark)
Autor: Antigravity AI
Soporte: Telegram Bot (@extractfh_bot) + UserBot Premium + Canal de Almacenamiento + Aria2c + yt-dlp + FFmpeg + Coolify
"""

import os
import re
import json
import sqlite3
import logging
import asyncio
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter, BadRequest, NetworkError, TimedOut
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

from leech_engine import (
    process_and_upload,
    process_channel_messages_and_unir,
    get_available_formats,
    human_readable_size,
    WATERMARK_FOOTER,
    STORAGE_CHANNEL_ID,
    DOWNLOAD_DIR
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configurar Logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("MultimediaBot")

# ==============================================================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==============================================================================
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "1601545124"))
DB_PATH = os.getenv("DB_PATH", "multimedia_cache.db")

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
PROWLARR_URL = os.getenv("PROWLARR_URL", "http://localhost:9696")
PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY", "")

PRIMARY_MODEL = "google/gemini-2.5-flash-lite"
FALLBACK_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

# Cola de mensajes multipartes por usuario (IDs en canal de almacenamiento)
USER_FORWARDED_QUEUE = {}

# ==============================================================================
# UTILIDADES DE MENSAJERÍA SEGURA (ANTI-ERRORES DE MARKDOWN)
# ==============================================================================
async def safe_reply_text(update: Update, text: str, reply_markup=None, photo=None):
    """Envía un mensaje de forma segura, soportando tanto mensajes directos como CallbackQuery."""
    # Determinar el objeto mensaje correcto (directo o callback)
    msg = update.message
    if msg is None and update.callback_query:
        msg = update.callback_query.message

    if msg is None:
        logger.error("safe_reply_text: No se encontró objeto mensaje en update.")
        return None

    try:
        if photo:
            return await msg.reply_photo(
                photo=photo,
                caption=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            return await msg.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.warning(f"Fallo Markdown, enviando como texto plano: {e}")
        try:
            if photo:
                return await msg.reply_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup
                )
            else:
                return await msg.reply_text(
                    text,
                    reply_markup=reply_markup
                )
        except Exception as e2:
            logger.error(f"Error definitivo al enviar mensaje: {e2}")
            return None

async def safe_edit_text(message, text: str, reply_markup=None):
    """Edita un mensaje de forma segura, ignorando errores de 'no modificado' y esperando en caso de FloodWait."""
    try:
        return await message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    except RetryAfter as e:
        logger.warning(f"FloodWait detectado por Telegram: esperando {e.retry_after}s...")
        await asyncio.sleep(e.retry_after)
        try:
            return await message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception:
            return None
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return None
        logger.warning(f"Fallo Markdown edit, intentando como texto plano: {e}")
        try:
            return await message.edit_text(
                text,
                reply_markup=reply_markup
            )
        except Exception:
            return None
    except Exception as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str:
            return None
        logger.warning(f"Fallo Markdown edit, enviando como texto plano: {e}")
        try:
            return await message.edit_text(
                text,
                reply_markup=reply_markup
            )
        except Exception as e2:
            if "message is not modified" not in str(e2).lower():
                logger.error(f"Error definitivo editando mensaje: {e2}")
            pass

# ==============================================================================
# SEGURIDAD: DECORADOR EXCLUSIVO PARA ADMIN
# ==============================================================================
def admin_only(func):
    """Restringe el acceso al bot única y exclusivamente a tu ID de Telegram."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.id != ADMIN_USER_ID:
            logger.warning(f"Acceso no autorizado ID: {user.id if user else 'Desconocido'}")
            if update.message:
                await safe_reply_text(
                    update,
                    f"⛔ *Acceso Denegado*\nEste bot es privado y exclusivo de su administrador.{WATERMARK_FOOTER}"
                )
            elif update.callback_query:
                await update.callback_query.answer("Acceso Denegado.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ==============================================================================
# BASE DE DATOS LOCAL Y CACHÉ (SQLite)
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS descargas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT UNIQUE,
            data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_from_cache(query):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM descargas WHERE query = ?", (query.lower().strip(),))
        row = cursor.fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
    except Exception:
        return None

def save_to_cache(query, data):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO descargas (query, data) VALUES (?, ?)",
            (query.lower().strip(), json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def delete_from_cache(query):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM descargas WHERE query LIKE ?", (f"%{query.lower().strip()}%",))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted
    except Exception:
        return 0

def get_db_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM descargas")
        count = cursor.fetchone()[0]
        size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        conn.close()
        return count, size_bytes / 1024
    except Exception:
        return 0, 0

def buscar_tmdb_serie(query):
    """Busca series/películas en TMDb y genera queries inteligentes de búsqueda."""
    if not TMDB_API_KEY:
        return None
    
    # Detectar número de capítulo/episodio en el query
    ep_match = re.search(r'(?:cap[ií]tulo|ep(?:isodio)?|cap|bolum|bölüm|episode)?\s*(\d{1,4})\s*$', query, re.IGNORECASE)
    episode_num = int(ep_match.group(1)) if ep_match else None
    show_name = query[:ep_match.start()].strip() if ep_match else query
    
    try:
        # Buscar la serie en TMDb
        search_url = f"https://api.themoviedb.org/3/search/tv?api_key={TMDB_API_KEY}&query={quote_plus(show_name)}&language=es-MX"
        r = requests.get(search_url, timeout=8)
        if r.status_code != 200:
            return None
        
        results = r.json().get("results", [])
        if not results:
            # Intentar como película
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={quote_plus(show_name)}&language=es-MX"
            r = requests.get(search_url, timeout=8)
            if r.status_code == 200:
                results = r.json().get("results", [])
            if not results:
                return None
            movie = results[0]
            return {
                "tipo": "pelicula",
                "titulo_es": movie.get("title", show_name),
                "titulo_original": movie.get("original_title", show_name),
                "año": (movie.get("release_date") or "")[:4],
                "poster_url": f"https://image.tmdb.org/t/p/w500{movie['poster_path']}" if movie.get("poster_path") else None,
                "sinopsis": movie.get("overview", "")[:200],
                "queries_sugeridos": [
                    f"{movie.get('title', show_name)} {(movie.get('release_date') or '')[:4]}",
                    movie.get("original_title", show_name),
                    f"{show_name} latino",
                    f"{show_name} español"
                ]
            }
        
        show = results[0]
        show_id = show["id"]
        titulo_es = show.get("name", show_name)
        titulo_original = show.get("original_name", show_name)
        poster = f"https://image.tmdb.org/t/p/w500{show['poster_path']}" if show.get("poster_path") else None
        
        result = {
            "tipo": "serie",
            "titulo_es": titulo_es,
            "titulo_original": titulo_original,
            "poster_url": poster,
            "sinopsis": show.get("overview", "")[:200],
            "episodio": episode_num,
            "temporada": None,
            "episodio_en_temporada": None,
            "queries_sugeridos": []
        }
        
        # Si hay número de episodio, calcular temporada/episodio
        if episode_num:
            details_url = f"https://api.themoviedb.org/3/tv/{show_id}?api_key={TMDB_API_KEY}&language=es-MX"
            dr = requests.get(details_url, timeout=8)
            if dr.status_code == 200:
                details = dr.json()
                seasons = details.get("seasons", [])
                ep_counter = 0
                for season in seasons:
                    s_num = season.get("season_number", 0)
                    if s_num == 0:  # Especiales
                        continue
                    ep_count = season.get("episode_count", 0)
                    if ep_counter + ep_count >= episode_num:
                        result["temporada"] = s_num
                        result["episodio_en_temporada"] = episode_num - ep_counter
                        break
                    ep_counter += ep_count
            
            s = result.get("temporada")
            e = result.get("episodio_en_temporada")
            se_code = f"S{s:02d}E{e:02d}" if s and e else ""
            
            result["queries_sugeridos"] = [
                f"{titulo_original} {se_code}" if se_code else f"{titulo_original} Episode {episode_num}",
                f"{titulo_original} Episode {episode_num}",
                f"{titulo_es} Capitulo {episode_num}",
                f"{titulo_es} {episode_num} español",
                f"{titulo_original} {episode_num} Bolum",
                f"{titulo_es} {episode_num} latino doblado"
            ]
        else:
            result["queries_sugeridos"] = [
                titulo_original,
                titulo_es,
                f"{titulo_es} español latino",
                f"{titulo_original} spanish"
            ]
        
        return result
    except Exception as e:
        logger.warning(f"Error buscando en TMDb: {e}")
        return None

def buscar_prowlarr(query, limit=8):
    """Busca torrents en todos los indexers de Prowlarr (TPB, showRSS, YTS, etc.)."""
    if not PROWLARR_API_KEY or not PROWLARR_URL:
        return []
    
    results = []
    ignorar = ["manyvids", "parody", "xxx", "porn", "hentai"]
    
    try:
        # Obtener lista de indexers
        idx_url = f"{PROWLARR_URL}/api/v1/indexer"
        idx_resp = requests.get(idx_url, headers={"X-Api-Key": PROWLARR_API_KEY}, timeout=10)
        if idx_resp.status_code != 200:
            return []
        
        indexers = idx_resp.json()
        
        for indexer in indexers:
            if not indexer.get("enable"):
                continue
            indexer_id = indexer.get("id")
            indexer_name = indexer.get("name", "Unknown")
            
            try:
                search_url = f"{PROWLARR_URL}/{indexer_id}/api"
                params = {"t": "search", "q": query, "apikey": PROWLARR_API_KEY}
                resp = requests.get(search_url, params=params, timeout=15)
                if resp.status_code != 200:
                    continue
                
                # Parsear XML Torznab
                root = ET.fromstring(resp.text)
                ns = {"torznab": "http://torznab.com/schemas/2015/feed"}
                
                for item in root.findall(".//item"):
                    title_el = item.find("title")
                    link_el = item.find("link")
                    size_el = item.find("size")
                    
                    if title_el is None:
                        continue
                    
                    name = title_el.text or ""
                    if any(bad in name.lower() for bad in ignorar):
                        continue
                    
                    # Obtener magnet o link de torrent
                    magnet = ""
                    link = link_el.text if link_el is not None else ""
                    
                    # Buscar magneturl en atributos torznab
                    for attr in item.findall("torznab:attr", ns):
                        if attr.get("name") == "magneturl":
                            magnet = attr.get("value", "")
                        elif attr.get("name") == "seeders":
                            seeders_val = attr.get("value", "0")
                    
                    if not magnet and link.startswith("magnet:"):
                        magnet = link
                    
                    if not magnet:
                        continue
                    
                    # Tamaño
                    size_bytes = int(size_el.text) if size_el is not None and size_el.text else 0
                    size_str = f"{size_bytes / (1024**3):.2f} GB" if size_bytes > 1024**3 else f"{size_bytes / (1024**2):.1f} MB"
                    
                    # Seeders
                    seeders = "0"
                    for attr in item.findall("torznab:attr", ns):
                        if attr.get("name") == "seeders":
                            seeders = attr.get("value", "0")
                    
                    results.append({
                        "nombre": name,
                        "peso": size_str,
                        "seeders": seeders,
                        "magnet": magnet,
                        "fuente": f"Prowlarr/{indexer_name}"
                    })
                    
                    if len(results) >= limit:
                        break
            except Exception as e:
                logger.debug(f"Error buscando en indexer {indexer_name}: {e}")
                continue
            
            if len(results) >= limit:
                break
    except Exception as e:
        logger.warning(f"Error conectando a Prowlarr: {e}")
    
    return results

def buscar_youtube_ytdlp(query, limit=3):
    """Busca videos en YouTube usando yt-dlp ytsearch (capítulos completos de series, películas, etc.)."""
    results = []
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch{limit * 2}:{query}", download=False)
            if not search_results or "entries" not in search_results:
                return []
            
            for entry in search_results["entries"]:
                if not entry:
                    continue
                duration = entry.get("duration") or 0
                # Solo videos de más de 15 minutos (capítulos completos)
                if duration >= 900:  # 15 minutos
                    dur_min = int(duration) // 60
                    results.append({
                        "nombre": entry.get("title", "Video YouTube"),
                        "servidor": f"YouTube ({dur_min} min)",
                        "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                        "duracion_min": dur_min
                    })
                    if len(results) >= limit:
                        break
    except Exception as e:
        logger.warning(f"Error buscando en YouTube: {e}")
    return results

# ==============================================================================
# MOTOR DE RASTREO MULTIMEDIA Y TRACKERS LIMPIOS
# ==============================================================================
def buscar_torrents_trackers(query, limit=5):
    palabras_ruido = ["latino", "castellano", "descargar", "4k", "1080p", "720p", "estreno", "completa", "hd"]
    clean_words = [w for w in query.split() if w.lower() not in palabras_ruido]
    clean_query = " ".join(clean_words) if clean_words else query

    url = f"https://apibay.org/q.php?q={quote_plus(clean_query)}"
    magnets = []
    ignorar = ["manyvids", "parody", "xxx", "porn", "hentai"]
    
    try:
        r = requests.get(url, timeout=7)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list) and data[0].get("id") != "0":
                for item in data:
                    name = item.get("name", "")
                    if any(bad in name.lower() for bad in ignorar):
                        continue
                        
                    info_hash = item.get("info_hash", "")
                    size_bytes = int(item.get("size", 0))
                    size_str = f"{size_bytes / (1024**3):.2f} GB" if size_bytes > 1024**3 else f"{size_bytes / (1024**2):.1f} MB"
                    seeders = item.get("seeders", 0)
                    magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={quote_plus(name)}"
                    
                    magnets.append({
                        "nombre": name,
                        "peso": size_str,
                        "seeders": seeders,
                        "magnet": magnet,
                        "fuente": "Trackers"
                    })
                    if len(magnets) >= limit:
                        break
    except Exception:
        pass
    return magnets

def buscar_plataformas_video(query, limit=3):
    url = f"https://api.dailymotion.com/videos?search={requests.utils.quote(query)}&limit=8&fields=id,title,url,duration"
    videos = []
    try:
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            data = r.json()
            for v in data.get("list", []):
                dur_sec = int(v.get("duration", 0))
                if dur_sec >= 600:
                    dur_min = dur_sec // 60
                    videos.append({
                        "nombre": v.get("title", "Ver Video"),
                        "servidor": f"Dailymotion ({dur_min} min)",
                        "url": v.get("url", "")
                    })
                    if len(videos) >= limit:
                        break
    except Exception:
        pass
    return videos

def buscar_urls_en_web(query, max_links=4):
    search_queries = [
        f"{query} descargar mega 1fichier drive",
        f"{query} capitulos completos ver online"
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    links = []
    
    for sq in search_queries:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(sq)}"
        try:
            resp = requests.get(search_url, headers=headers, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", class_="result__url", href=True):
                    raw_url = a['href']
                    if "uddg=" in raw_url:
                        clean = requests.utils.unquote(raw_url.split("uddg=")[1].split("&")[0])
                        if clean not in links:
                            links.append(clean)
                    elif raw_url.startswith("http") and raw_url not in links:
                        links.append(raw_url)
                    if len(links) >= max_links:
                        break
        except Exception:
            pass
        if len(links) >= max_links:
            break
            
    return links

def descargar_pagina(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"}, timeout=6)
        if r.status_code == 200 and len(r.text) > 300:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "svg"]):
                tag.extract()
            text = soup.get_text(separator=" ", strip=True)
            magnets = [a['href'] for a in soup.find_all('a', href=True) if a['href'].startswith('magnet:?xt=')]
            return {"url": url, "text": text[:4000], "magnets": magnets}
    except Exception:
        pass
    return None

def extraer_multiples_fuentes_con_ia(paginas, titulo_busqueda, model_name=PRIMARY_MODEL):
    if not paginas:
        return None

    contexto_unificado = ""
    for i, p in enumerate(paginas, 1):
        contexto_unificado += f"\n--- FUENTE #{i} ({p['url']}) ---\n{p['text']}\n"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""
Analiza las siguientes fuentes para '{titulo_busqueda}' y extrae enlaces válidos:
- Descargas Directas (Mega, 1Fichier, Drive, Mediafire).
- Streaming de capítulos completos o películas.
- Magnets y calidades.

FUENTES:
{contexto_unificado[:18000]}

Devuelve JSON:
{{
  "titulo": "...",
  "calidad_detectada": "1080p / 720p / 4K / HD",
  "idioma_detectado": "Latino / Castellano / Sub / Original",
  "poster_url": "URL o null",
  "descargas_directas": [
      {{"servidor": "Mega", "calidad": "1080p", "url": "https://..."}}
  ],
  "reproductores_online": [
      {{"servidor": "Servidor", "url": "https://..."}}
  ],
  "magnets_encontrados": [
      {{"nombre": "...", "magnet": "magnet:?..."}}
  ]
}}
"""
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }

    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if res.status_code == 200:
            raw_content = res.json()["choices"][0]["message"]["content"]
            # Limpiar code fences si el modelo los incluyó
            cleaned = re.sub(r'^```(?:json)?\s*', '', raw_content.strip())
            cleaned = re.sub(r'\s*```$', '', cleaned)
            return json.loads(cleaned)
        elif res.status_code in [404, 429] and model_name != FALLBACK_MODEL:
            return extraer_multiples_fuentes_con_ia(paginas, titulo_busqueda, model_name=FALLBACK_MODEL)
    except Exception:
        pass
    return None

def procesar_busqueda_universal(query):
    """Motor de búsqueda universal con TMDb + Prowlarr + YouTube + Trackers + IA."""
    cached = get_from_cache(query)
    if cached:
        return cached, True

    # 1. Metadata de TMDb (identifica series/películas y genera queries inteligentes)
    tmdb_info = buscar_tmdb_serie(query)
    
    # 2. Generar lista de queries de búsqueda
    search_queries = [query]
    if tmdb_info and tmdb_info.get("queries_sugeridos"):
        search_queries = tmdb_info["queries_sugeridos"][:4] + [query]
        # Eliminar duplicados preservando orden
        seen = set()
        unique_queries = []
        for q in search_queries:
            q_lower = q.lower().strip()
            if q_lower and q_lower not in seen:
                seen.add(q_lower)
                unique_queries.append(q)
        search_queries = unique_queries

    # 3. Buscar en Prowlarr (todos los indexers: TPB, showRSS, YTS)
    prowlarr_results = []
    for sq in search_queries[:3]:
        prowlarr_results.extend(buscar_prowlarr(sq, limit=4))
        if len(prowlarr_results) >= 6:
            break
    
    # 4. Buscar en ApiBay directamente (backup si Prowlarr no devuelve nada)
    tracker_results = []
    if len(prowlarr_results) < 2:
        for sq in search_queries[:2]:
            tracker_results.extend(buscar_torrents_trackers(sq, limit=3))
            if tracker_results:
                break

    # 5. Buscar en YouTube (capítulos completos de series)
    youtube_results = []
    for sq in search_queries[:2]:
        youtube_results = buscar_youtube_ytdlp(sq, limit=3)
        if youtube_results:
            break

    # 6. Buscar en Dailymotion
    video_platform_results = buscar_plataformas_video(query, limit=2)
    
    # 7. Web scraping + IA (fallback)
    urls = buscar_urls_en_web(query, max_links=3)
    paginas = []
    if urls:
        with ThreadPoolExecutor(max_workers=3) as executor:
            paginas = list(filter(None, executor.map(descargar_pagina, urls)))
    ia_data = extraer_multiples_fuentes_con_ia(paginas, query) if paginas else {}

    # 8. Compilar resultado final
    all_trackers = prowlarr_results + tracker_results
    # Deduplicar por magnet hash
    seen_hashes = set()
    unique_trackers = []
    for t in all_trackers:
        magnet = t.get("magnet", "")
        hash_match = re.search(r"urn:btih:([a-zA-Z0-9]+)", magnet, re.IGNORECASE)
        h = hash_match.group(1).lower() if hash_match else magnet
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_trackers.append(t)

    # Usar titulo de TMDb si existe
    titulo = query
    poster_url = None
    if tmdb_info:
        titulo = tmdb_info.get("titulo_es", query)
        if tmdb_info.get("episodio"):
            titulo += f" - Capítulo {tmdb_info['episodio']}"
        poster_url = tmdb_info.get("poster_url")

    all_reproductores = youtube_results + video_platform_results
    if ia_data and ia_data.get("reproductores_online"):
        all_reproductores += ia_data["reproductores_online"]

    resultado_final = {
        "titulo": ia_data.get("titulo", titulo) if ia_data else titulo,
        "calidad": ia_data.get("calidad_detectada", "Detectada") if ia_data else "Multi-Calidad",
        "idioma": ia_data.get("idioma_detectado", "Multi-Audio") if ia_data else "Varios",
        "poster_url": poster_url or (ia_data.get("poster_url") if ia_data else None),
        "opciones_trackers": unique_trackers,
        "descargas_directas": ia_data.get("descargas_directas", []) if ia_data else [],
        "reproductores_online": all_reproductores,
        "tmdb_info": tmdb_info
    }

    if ia_data and ia_data.get("magnets_encontrados"):
        for m in ia_data["magnets_encontrados"]:
            resultado_final["opciones_trackers"].append({
                "nombre": m.get("nombre", "Opción Web"),
                "peso": "N/A",
                "seeders": "-",
                "magnet": m.get("magnet", ""),
                "fuente": "Web Scrape"
            })

    tiene_datos = (
        bool(resultado_final["opciones_trackers"]) or
        bool(resultado_final["descargas_directas"]) or
        bool(resultado_final["reproductores_online"])
    )

    if tiene_datos:
        save_to_cache(query, resultado_final)
        return resultado_final, False

    return None, False

# ==============================================================================
# PIPELINE DE DESCARGA Y SUBIDA
# ==============================================================================
async def handle_download_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE, url_or_file: str, height_limit=None, extract_audio=False, title_hint="", is_local_file=False):
    status_msg = await safe_reply_text(
        update,
        f"⚡ *Iniciando procesamiento de video/archivo...*\n🔗 `{url_or_file[:80]}...`{WATERMARK_FOOTER}"
    )

    async def update_status_text(new_text):
        if status_msg:
            await safe_edit_text(status_msg, new_text)

    chat_id = update.effective_chat.id
    user_username = update.effective_user.username if update.effective_user else None
    bot_instance = context.bot

    asyncio.create_task(
        process_and_upload(
            url_or_file=url_or_file,
            chat_id=chat_id,
            status_updater=update_status_text,
            bot_instance=bot_instance,
            title_hint=title_hint,
            height_limit=height_limit,
            extract_audio=extract_audio,
            is_local_file=is_local_file,
            user_username=user_username
        )
    )

# ==============================================================================
# MANEJADOR DE DOCUMENTOS Y ARCHIVOS MULTIPARTE (RAR / ZIP / 7Z)
# ==============================================================================
@admin_only
async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Recibe documentos (incluso de 1.45 GB - 4 GB), los reenvía al canal de almacenamiento
    y los encola para que Telethon MTProto los descargue y una cuando el usuario ejecute /unir.
    """
    doc = update.message.document or update.message.video or update.message.audio
    if not doc:
        return

    user_id = update.effective_user.id
    file_name = doc.file_name if hasattr(doc, 'file_name') and doc.file_name else f"file_{doc.file_id[:8]}.mp4"
    file_size = doc.file_size or 0

    try:
        # Reenviar el archivo de cualquier tamaño (hasta 4GB) al canal de almacenamiento
        forwarded = await context.bot.forward_message(
            chat_id=STORAGE_CHANNEL_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )

        if user_id not in USER_FORWARDED_QUEUE:
            USER_FORWARDED_QUEUE[user_id] = []

        USER_FORWARDED_QUEUE[user_id].append(forwarded.message_id)
        partes_total = len(USER_FORWARDED_QUEUE[user_id])

        await safe_reply_text(
            update,
            f"📦 *Parte Registrada:* `{file_name}` (`{human_readable_size(file_size)}`)\n"
            f"📊 *Partes acumuladas:* `{partes_total}`\n\n"
            f"💡 _Envía las siguientes partes y luego escribe_ `/unir` _para descargarlas con la cuenta Premium Jin y fusionar el video completo._"
            f"{WATERMARK_FOOTER}"
        )
    except Exception as e:
        logger.error(f"Error al reenviar archivo al canal: {e}")
        await safe_reply_text(
            update,
            f"❌ *Error registrando archivo:* Asegúrate de que el bot sea administrador del canal `{STORAGE_CHANNEL_ID}`.\nDetalle: `{str(e)}`"
            f"{WATERMARK_FOOTER}"
        )

@admin_only
async def cmd_unir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Descarga todas las partes acumuladas desde el canal privado con MTProto (Jin) y las fusiona con FFmpeg."""
    user_id = update.effective_user.id
    message_ids = USER_FORWARDED_QUEUE.pop(user_id, [])
    
    if not message_ids:
        await safe_reply_text(
            update,
            f"⚠️ *No tienes partes de archivos registradas.*\n"
            f"Reenvía primero los archivos `.part1.rar`, `.part2.rar`, etc. a este chat y luego escribe `/unir`."
            f"{WATERMARK_FOOTER}"
        )
        return

    status = await safe_reply_text(
        update,
        f"🚀 *Iniciando descarga y fusión de {len(message_ids)} partes...*\n"
        f"💎 *Usando motor Telethon MTProto (Jin) + 7zip + FFmpeg...*"
        f"{WATERMARK_FOOTER}"
    )

    async def update_status_text(new_text):
        if status:
            await safe_edit_text(status, new_text)

    chat_id = update.effective_chat.id
    user_username = update.effective_user.username if update.effective_user else None
    bot_instance = context.bot

    asyncio.create_task(
        process_channel_messages_and_unir(
            channel_id=STORAGE_CHANNEL_ID,
            message_ids=message_ids,
            chat_id=chat_id,
            status_updater=update_status_text,
            bot_instance=bot_instance,
            title_hint="Pelicula_Completa_Fusionada",
            user_username=user_username
        )
    )

# ==============================================================================
# CONTROLADORES DE TELEGRAM
# ==============================================================================
@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🎬 *¡Bienvenido al Bot Multimedia Universal & Leech Premium!*\n"
        "🔒 *Acceso Administrador Verificado (`ID: 1601545124`)*\n\n"
        "🚀 *Capacidades del Sistema:*\n"
        "1. 📥 **Descarga Directa en Este Chat:** Pega cualquier enlace de YouTube, TikTok, Instagram, Facebook o Torrent.\n"
        "2. 🗜️ **Reenvío de Archivos RAR Grandes:** Reenvía los `.part1.rar`, `.part2.rar` a este bot y usa `/unir` para recibir el video completo.\n"
        "3. 🧲 **Descarga de Torrents:** Descarga películas completas desde magnets y trackers a máxima velocidad con Aria2c.\n"
        "4. 🎛️ **Selector de Calidad:** Usa `/calidad <url>` para elegir 1080p, 720p o MP3.\n"
        "5. 🔎 **Búsqueda Universal:** Escribe el nombre de cualquier Película, Serie o Reality.\n"
        "6. 🎬 **Búsqueda de Series:** Usa `/serie Nombre Capítulo` para buscar en TMDb, Prowlarr y YouTube.\n"
        f"{WATERMARK_FOOTER}"
    )
    await safe_reply_text(update, msg)

@admin_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *Guía de Comandos:*\n\n"
        "• 📥 **Descarga Directa:** Pega el enlace de YouTube, Instagram, TikTok, Facebook, X o Torrent Magnet.\n"
        "• 🗜️ **Unir Archivos RAR:** Reenvía los `.part1.rar`, `.part2.rar` a este bot y escribe `/unir`.\n"
        "• 🎛️ **Elegir Calidad:** `/calidad <url>`\n"
        "• 🔎 **Búsqueda:** `/buscar <título>` o escribe el nombre directamente.\n"
        "• 🎬 **Buscar Serie/Capítulo:** `/serie <título> <capítulo>`\n"
        "• 📥 **Descargar Enlace:** `/descargar <url>`\n"
        "• 📊 **Estadísticas:** `/stats`\n"
        "• 🗑️ **Limpiar Caché:** `/borrar <título>`"
        f"{WATERMARK_FOOTER}"
    )
    await safe_reply_text(update, msg)

@admin_only
async def cmd_calidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply_text(update, f"⚠️ Envía el enlace. Ejemplo: `/calidad https://www.youtube.com/watch?v=...`{WATERMARK_FOOTER}")
        return

    url = context.args[0]
    status = await safe_reply_text(update, f"🔍 *Analizando calidades disponibles del video...*{WATERMARK_FOOTER}")
    
    info = await asyncio.to_thread(get_available_formats, url)
    if not info:
        if status:
            await safe_edit_text(status, f"❌ No se pudieron extraer las calidades. Descargando en mejor calidad disponible...{WATERMARK_FOOTER}")
        await handle_download_pipeline(update, context, url)
        return

    title = info.get("title", "Video")
    resoluciones = info.get("resoluciones", [])

    keyboard = []
    for res in resoluciones[:4]:
        keyboard.append([InlineKeyboardButton(f"📺 Descargar en {res}p", callback_data=f"dl|{res}|{url}")])
    
    keyboard.append([InlineKeyboardButton("✨ Mejor Calidad (Auto)", callback_data=f"dl|best|{url}")])
    keyboard.append([InlineKeyboardButton("🎵 Extraer Solo Audio (MP3)", callback_data=f"dl|audio|{url}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if status:
        await safe_edit_text(
            status,
            f"🎬 *{title}*\n\n👇 *Selecciona la calidad deseada para recibir en este chat:*{WATERMARK_FOOTER}",
            reply_markup=reply_markup
        )

@admin_only
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data

    if data.startswith("dl|"):
        parts = data.split("|", 2)
        choice = parts[1]
        url = parts[2]
        await safe_edit_text(query.message, f"🚀 *Iniciando descarga en formato:* `{choice}`...{WATERMARK_FOOTER}")
        if choice == "audio":
            await handle_download_pipeline(update, context, url, extract_audio=True)
        elif choice == "best":
            await handle_download_pipeline(update, context, url)
        else:
            height = int(choice) if choice.isdigit() else None
            await handle_download_pipeline(update, context, url, height_limit=height)

    elif data.startswith("mag|"):
        magnet_hash = data.split("|", 1)[1]
        magnet_uri = f"magnet:?xt=urn:btih:{magnet_hash}"
        await safe_edit_text(query.message, f"🧲 *Iniciando descarga del Torrent en el VPS...*\n`{magnet_uri}`{WATERMARK_FOOTER}")
        await handle_download_pipeline(update, context, magnet_uri, title_hint="Pelicula_Torrent")

@admin_only
async def cmd_serie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Búsqueda inteligente de series/novelas por nombre y capítulo."""
    if not context.args:
        await safe_reply_text(update, f"⚠️ Envía nombre y capítulo. Ejemplo: `/serie Emanet 350`{WATERMARK_FOOTER}")
        return
    
    query = " ".join(context.args)
    status = await safe_reply_text(
        update,
        f"🔍 *Buscando serie:* `{query}`\n"
        f"📡 *Consultando TMDb + Prowlarr + YouTube + Trackers...*{WATERMARK_FOOTER}"
    )
    
    data, is_cache = procesar_busqueda_universal(query)
    
    if not data:
        if status:
            await safe_edit_text(
                status,
                f"❌ No encontré resultados para *{query}*.\n"
                f"💡 Intenta: `/serie NombreSerie NúmeroCapítulo`\n"
                f"Ejemplo: `/serie Emanet 350` o `/serie Kara Sevda 50`{WATERMARK_FOOTER}"
            )
        return
    
    # Mismo flujo de presentación que main_message_handler
    tmdb = data.get("tmdb_info", {})
    origen = "⚡ _(Caché)_" if is_cache else "🌐 _(Búsqueda en vivo)_"
    
    texto = f"🎬 *{data.get('titulo', query)}* {origen}\n\n"
    
    if tmdb:
        if tmdb.get("titulo_original") and tmdb["titulo_original"] != data.get("titulo", ""):
            texto += f"🏷️ *Original:* `{tmdb['titulo_original']}`\n"
        if tmdb.get("temporada") and tmdb.get("episodio_en_temporada"):
            texto += f"📺 *Temporada {tmdb['temporada']}* — *Episodio {tmdb['episodio_en_temporada']}*\n"
        if tmdb.get("sinopsis"):
            texto += f"📝 _{tmdb['sinopsis']}_\n"
    
    texto += f"\n📺 *Calidad:* `{data.get('calidad', 'Detectada')}`\n"
    texto += f"🔊 *Idioma:* `{data.get('idioma', 'N/A')}`\n"
    
    keyboard = []
    
    trackers = data.get("opciones_trackers", [])
    if trackers:
        texto += "\n🧲 *Torrents encontrados:*\n"
        for i, t in enumerate(trackers[:5], 1):
            nombre = t.get("nombre", f"Opción #{i}")
            peso = t.get("peso", "")
            seeds = f" | 🌱 {t.get('seeders')} seeds" if t.get("seeders") != "-" else ""
            fuente = t.get("fuente", "")
            texto += f"• *#{i}* [{peso}{seeds}] _({fuente})_\n"
            
            magnet = t.get("magnet", "")
            hash_match = re.search(r"urn:btih:([a-zA-Z0-9]+)", magnet)
            if hash_match:
                keyboard.append([InlineKeyboardButton(f"⬇️ Torrent #{i} [{peso}]", callback_data=f"mag|{hash_match.group(1)}")])
    
    for ddl in data.get("descargas_directas", [])[:3]:
        srv = ddl.get("servidor", "Descarga")
        url = ddl.get("url", "")
        if url.startswith("http"):
            keyboard.append([InlineKeyboardButton(f"☁️ {srv}", url=url)])
    
    reproductores = data.get("reproductores_online", [])
    if reproductores:
        texto += "\n▶️ *Streaming:*\n"
        for st in reproductores[:4]:
            srv = st.get("servidor", st.get("nombre", "Ver Video"))
            url = st.get("url", "")
            if url.startswith("http"):
                keyboard.append([InlineKeyboardButton(f"▶️ {srv}", url=url)])
    
    texto += WATERMARK_FOOTER
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    if status:
        try:
            await status.delete()
        except Exception:
            pass
    
    poster = data.get("poster_url")
    if poster and poster.startswith("http") and not poster.endswith(".ico"):
        await safe_reply_text(update, texto, photo=poster, reply_markup=reply_markup)
    else:
        await safe_reply_text(update, texto, reply_markup=reply_markup)

@admin_only
async def cmd_descargar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply_text(update, f"⚠️ Indica el link. Ejemplo: `/descargar https://...`{WATERMARK_FOOTER}")
        return
    await handle_download_pipeline(update, context, context.args[0])

@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count, size_kb = get_db_stats()
    tmdb_status = "✅ Activo" if TMDB_API_KEY else "❌ Inactivo"
    prowlarr_status = "✅ Activo" if PROWLARR_API_KEY and PROWLARR_URL else "❌ Inactivo"
    msg = (
        "📊 *Estadísticas del Sistema:*\n\n"
        f"• 💾 *Contenidos en Caché:* `{count}`\n"
        f"• 📁 *Tamaño de BD:* `{size_kb:.2f} KB`\n"
        f"• 🤖 *Motor IA:* `{PRIMARY_MODEL}`\n"
        f"• 🧲 *Motor Torrent:* `Aria2c Activo`\n"
        f"• 💎 *UserBot Premium:* `4 GB / MTProto (Jin)`\n"
        f"• 🎬 *TMDb API:* `{tmdb_status}`\n"
        f"• 🔎 *Prowlarr API:* `{prowlarr_status}`\n"
        f"• 📦 *Canal de Almacenamiento:* `{STORAGE_CHANNEL_ID}`\n"
        f"• 👤 *Administrador:* `{ADMIN_USER_ID}`\n"
        f"{WATERMARK_FOOTER}"
    )
    await safe_reply_text(update, msg)

@admin_only
async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply_text(update, f"⚠️ Indica el nombre a borrar.{WATERMARK_FOOTER}")
        return
    query = " ".join(context.args)
    deleted = delete_from_cache(query)
    if deleted > 0:
        await safe_reply_text(update, f"✅ Se eliminó *{query}* de la memoria.{WATERMARK_FOOTER}")
    else:
        await safe_reply_text(update, f"ℹ️ No se encontró *{query}* en la base de datos.{WATERMARK_FOOTER}")

@admin_only
async def main_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    # Si es un enlace Magnet
    if text.startswith("magnet:?"):
        await handle_download_pipeline(update, context, text, title_hint="Torrent_Download")
        return

    # Si es un enlace directo a video o red social
    if re.match(r"^https?://", text):
        await handle_download_pipeline(update, context, text)
        return

    # Auto-detectar búsqueda de serie con capítulo
    ep_pattern = re.search(r'(?:cap[ií]tulo|ep(?:isodio)?|cap|bolum|bölüm|episode)?\s*(\d{1,4})\s*$', text, re.IGNORECASE)
    if ep_pattern:
        # Tiene número de episodio, tratar como búsqueda de serie
        pass  # El flujo de procesar_busqueda_universal ya maneja esto con TMDb

    # Búsqueda multimedia universal
    status = await safe_reply_text(
        update,
        f"🔎 *Buscando:* `{text}`\n"
        f"⏳ *Rastreando Redes de Torrents, Servidores DDL y Plataformas de Video...*{WATERMARK_FOOTER}"
    )

    data, is_cache = procesar_busqueda_universal(text)

    if not data:
        if status:
            await safe_edit_text(
                status,
                f"❌ No encontré enlaces disponibles para *{text}*.\n"
                f"💡 Prueba simplificando el nombre (ej. `Spider Man 4K` o `Gladiador 2`).{WATERMARK_FOOTER}"
            )
        return

    origen = "⚡ _(Desde Base de Datos Local)_" if is_cache else "🌐 _(Agregado de Múltiples Fuentes)_"

    texto = (
        f"🎬 *{data.get('titulo', text)}* {origen}\n\n"
        f"📺 *Calidad:* `{data.get('calidad', 'Detectada')}`\n"
        f"🔊 *Idioma:* `{data.get('idioma', 'N/A')}`\n"
    )

    keyboard = []

    trackers = data.get("opciones_trackers", [])
    if trackers:
        texto += "\n🧲 *Opciones Torrent / Magnet:* \n"
        for i, t in enumerate(trackers[:3], 1):
            nombre = t.get("nombre", f"Opción #{i}")
            peso = t.get("peso", "")
            seeds = f" | 🌱 {t.get('seeders')} seeds" if t.get("seeders") != "-" else ""
            fuente = t.get("fuente", "")
            texto += f"• *#{i}* [{peso}{seeds}] _({fuente})_\n`{nombre}`\n\n"
            
            magnet = t.get("magnet", "")
            hash_match = re.search(r"urn:btih:([a-zA-Z0-9]+)", magnet)
            if hash_match:
                btn_hash = hash_match.group(1)
                keyboard.append([InlineKeyboardButton(f"⬇️ Descargar Torrent #{i} [{peso}]", callback_data=f"mag|{btn_hash}")])

    for ddl in data.get("descargas_directas", [])[:4]:
        srv = ddl.get("servidor", "Descarga Directa")
        url = ddl.get("url", "")
        if url.startswith("http"):
            keyboard.append([InlineKeyboardButton(f"☁️ {srv}", url=url)])

    for st in data.get("reproductores_online", [])[:4]:
        srv = st.get("servidor", st.get("nombre", "Ver Video"))
        url = st.get("url", "")
        if url.startswith("http"):
            if "youtube.com" in url or "youtu.be" in url:
                keyboard.append([InlineKeyboardButton(f"📥 Descargar {srv}", callback_data=f"dl|best|{url}")])
            else:
                keyboard.append([InlineKeyboardButton(f"▶️ {srv}", url=url)])

    texto += WATERMARK_FOOTER

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    if status:
        try:
            await status.delete()
        except Exception:
            pass

    poster = data.get("poster_url")
    if poster and poster.startswith("http") and not poster.endswith(".ico"):
        await safe_reply_text(
            update,
            texto,
            photo=poster,
            reply_markup=reply_markup
        )
        return

    await safe_reply_text(update, texto, reply_markup=reply_markup)

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja de forma silenciosa y robusta desconexiones temporales de red y timeouts."""
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning(f"Reconexión de red gestionada automáticamente: {err}")
    else:
        logger.error(f"Excepción en bot_multimedia: {err}", exc_info=err)

# ==============================================================================
# ARRANQUE DEL BOT
# ==============================================================================
def main():
    init_db()
    logger.info("🤖 Inicializando Bot Multimedia Universal + Leech...")
    logger.info(f"🔒 Restringido al Administrador ID: {ADMIN_USER_ID}")
    logger.info(f"📦 Canal de Almacenamiento: {STORAGE_CHANNEL_ID}")

    request_cfg = HTTPXRequest(
        connection_pool_size=30,
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=60.0,
        http_version="1.1"
    )

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request_cfg).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ayuda", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("borrar", cmd_borrar))
    app.add_handler(CommandHandler("calidad", cmd_calidad))
    app.add_handler(CommandHandler("unir", cmd_unir))
    app.add_handler(CommandHandler("serie", cmd_serie))
    app.add_handler(CommandHandler("descargar", cmd_descargar))
    app.add_handler(CommandHandler("buscar", main_message_handler))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Manejador de documentos y multipartes (.part1.rar, .zip, etc.)
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_document_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_message_handler))

    logger.info("✅ Bot escuchando mensajes correctamente con HTTPX Turbo + Kurigram MTProto.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
