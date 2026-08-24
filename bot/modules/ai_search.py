"""
Módulo de Búsqueda Universal con IA + TMDb + Prowlarr + Trackers + OpenRouter LLM
Integrado nativamente en el ecosistema Mirror-Leech Telegram Bot
"""

import os
import re
import json
import sqlite3
import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified, FloodWait

from .. import LOGGER, bot_loop
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task, sync_to_async
from ..helper.telegram_helper.message_utils import send_message, edit_message, delete_message
from ..helper.telegram_helper.button_build import ButtonMaker
from .mirror_leech import Mirror

# Base de datos en memoria / archivo para guardar resultados temporales de búsqueda
SEARCH_SESSION_CACHE = {}

# ==============================================================================
# BASE DE DATOS LOCAL Y CACHÉ (SQLite)
# ==============================================================================
def get_db_connection():
    db_path = Config.DB_PATH or "multimedia_cache.db"
    conn = sqlite3.connect(db_path)
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
    return conn

def get_from_cache(query: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM descargas WHERE query = ?", (query.lower().strip(),))
        row = cursor.fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
    except Exception as e:
        LOGGER.debug(f"Cache get error: {e}")
        return None

def save_to_cache(query: str, data: dict):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO descargas (query, data) VALUES (?, ?)",
            (query.lower().strip(), json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        LOGGER.debug(f"Cache save error: {e}")

# ==============================================================================
# MOTOR TMDB: METADATOS Y RESOLUCIÓN INTELIGENTE DE SERIES / PELÍCULAS
# ==============================================================================
def buscar_tmdb_serie(query: str):
    """Busca en TMDb y genera queries inteligentes de búsqueda."""
    api_key = Config.TMDB_API_KEY
    if not api_key:
        return None

    # Detectar número de capítulo o episodio
    ep_match = re.search(r'(?:cap[ií]tulo|ep(?:isodio)?|cap|bolum|bölüm|episode)?\s*(\d{1,4})\s*$', query, re.IGNORECASE)
    episode_num = int(ep_match.group(1)) if ep_match else None
    show_name = query[:ep_match.start()].strip() if ep_match else query

    try:
        search_url = f"https://api.themoviedb.org/3/search/tv?api_key={api_key}&query={quote_plus(show_name)}&language=es-MX"
        r = requests.get(search_url, timeout=8)
        if r.status_code != 200:
            return None

        results = r.json().get("results", [])
        if not results:
            # Probar como película
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={quote_plus(show_name)}&language=es-MX"
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
                "sinopsis": movie.get("overview", "")[:300],
                "queries_sugeridos": [
                    f"{movie.get('title', show_name)} {(movie.get('release_date') or '')[:4]}",
                    movie.get("original_title", show_name),
                    f"{show_name} latino",
                    f"{show_name} castellano",
                    f"{show_name} 1080p"
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
            "sinopsis": show.get("overview", "")[:300],
            "episodio": episode_num,
            "temporada": None,
            "episodio_en_temporada": None,
            "queries_sugeridos": []
        }

        if episode_num:
            details_url = f"https://api.themoviedb.org/3/tv/{show_id}?api_key={api_key}&language=es-MX"
            dr = requests.get(details_url, timeout=8)
            if dr.status_code == 200:
                details = dr.json()
                seasons = details.get("seasons", [])
                ep_counter = 0
                for season in seasons:
                    s_num = season.get("season_number", 0)
                    if s_num == 0:
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
        LOGGER.warning(f"Error en TMDb: {e}")
        return None

# ==============================================================================
# MOTOR PROWLARR: INDEXERS TORZNAB (TPB, SHOWRSS, YTS, ETC.)
# ==============================================================================
def buscar_prowlarr(query: str, limit=8):
    prowlarr_url = Config.PROWLARR_URL
    prowlarr_key = Config.PROWLARR_API_KEY
    if not prowlarr_url or not prowlarr_key:
        return []

    results = []
    ignorar = ["manyvids", "parody", "xxx", "porn", "hentai"]

    try:
        idx_url = f"{prowlarr_url.rstrip('/')}/api/v1/indexer"
        idx_resp = requests.get(idx_url, headers={"X-Api-Key": prowlarr_key}, timeout=10)
        if idx_resp.status_code != 200:
            return []

        indexers = idx_resp.json()
        for indexer in indexers:
            if not indexer.get("enable"):
                continue
            indexer_id = indexer.get("id")
            indexer_name = indexer.get("name", "Indexer")

            try:
                search_url = f"{prowlarr_url.rstrip('/')}/{indexer_id}/api"
                params = {"t": "search", "q": query, "apikey": prowlarr_key}
                resp = requests.get(search_url, params=params, timeout=12)
                if resp.status_code != 200:
                    continue

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

                    magnet = ""
                    link = link_el.text if link_el is not None else ""

                    for attr in item.findall("torznab:attr", ns):
                        if attr.get("name") == "magneturl":
                            magnet = attr.get("value", "")
                        elif attr.get("name") == "seeders":
                            seeders_val = attr.get("value", "0")

                    if not magnet and link.startswith("magnet:"):
                        magnet = link

                    if not magnet:
                        continue

                    size_bytes = int(size_el.text) if size_el is not None and size_el.text else 0
                    size_str = f"{size_bytes / (1024**3):.2f} GB" if size_bytes > 1024**3 else f"{size_bytes / (1024**2):.1f} MB"

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
            except Exception:
                continue

            if len(results) >= limit:
                break
    except Exception as e:
        LOGGER.warning(f"Error conectando a Prowlarr: {e}")

    return results

# ==============================================================================
# MOTOR TRACKERS: APIBAY FALLBACK
# ==============================================================================
def buscar_torrents_trackers(query: str, limit=5):
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
                        "fuente": "ApiBay"
                    })
                    if len(magnets) >= limit:
                        break
    except Exception:
        pass
    return magnets

# ==============================================================================
# MOTOR VIDEO: YT-DLP Y DAILYMOTION
# ==============================================================================
def buscar_youtube_ytdlp(query: str, limit=3):
    results = []
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
        if os.path.exists("cookies.txt"):
            ydl_opts["cookiefile"] = "cookies.txt"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch{limit * 2}:{query}", download=False)
            if not search_results or "entries" not in search_results:
                return []

            for entry in search_results["entries"]:
                if not entry:
                    continue
                duration = entry.get("duration") or 0
                if duration >= 900:  # Mayor a 15 minutos (capítulos completos)
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
        LOGGER.warning(f"Error buscando en YouTube: {e}")
    return results

def buscar_plataformas_video(query: str, limit=3):
    url = f"https://api.dailymotion.com/videos?search={quote_plus(query)}&limit=8&fields=id,title,url,duration"
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

# ==============================================================================
# MOTOR IA: OPENROUTER LLM EXTRACTOR
# ==============================================================================
def buscar_urls_en_web(query: str, max_links=4):
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

def descargar_pagina(url: str):
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

def extraer_multiples_fuentes_con_ia(paginas: list, titulo_busqueda: str, model_name=None):
    if not paginas or not Config.OPENROUTER_API_KEY:
        return None

    if not model_name:
        model_name = Config.PRIMARY_MODEL

    contexto_unificado = ""
    for i, p in enumerate(paginas, 1):
        contexto_unificado += f"\n--- FUENTE #{i} ({p['url']}) ---\n{p['text']}\n"

    headers = {
        "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
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
            cleaned = re.sub(r'^```(?:json)?\s*', '', raw_content.strip())
            cleaned = re.sub(r'\s*```$', '', cleaned)
            return json.loads(cleaned)
        elif res.status_code in [404, 429] and model_name != Config.FALLBACK_MODEL:
            return extraer_multiples_fuentes_con_ia(paginas, titulo_busqueda, model_name=Config.FALLBACK_MODEL)
    except Exception as e:
        LOGGER.warning(f"Error en OpenRouter IA: {e}")
    return None

# ==============================================================================
# PIPELINE DE BÚSQUEDA UNIVERSAL
# ==============================================================================
def procesar_busqueda_universal(query: str):
    cached = get_from_cache(query)
    if cached:
        return cached, True

    tmdb_info = buscar_tmdb_serie(query)

    search_queries = [query]
    if tmdb_info and tmdb_info.get("queries_sugeridos"):
        search_queries = tmdb_info["queries_sugeridos"][:4] + [query]
        seen = set()
        unique_queries = []
        for q in search_queries:
            q_lower = q.lower().strip()
            if q_lower and q_lower not in seen:
                seen.add(q_lower)
                unique_queries.append(q)
        search_queries = unique_queries

    prowlarr_results = []
    for sq in search_queries[:3]:
        prowlarr_results.extend(buscar_prowlarr(sq, limit=4))
        if len(prowlarr_results) >= 6:
            break

    tracker_results = []
    if len(prowlarr_results) < 2:
        for sq in search_queries[:2]:
            tracker_results.extend(buscar_torrents_trackers(sq, limit=3))
            if tracker_results:
                break

    youtube_results = []
    for sq in search_queries[:2]:
        youtube_results = buscar_youtube_ytdlp(sq, limit=3)
        if youtube_results:
            break

    video_platform_results = buscar_plataformas_video(query, limit=2)

    urls = buscar_urls_en_web(query, max_links=3)
    paginas = []
    if urls:
        with ThreadPoolExecutor(max_workers=3) as executor:
            paginas = list(filter(None, executor.map(descargar_pagina, urls)))
    ia_data = extraer_multiples_fuentes_con_ia(paginas, query) if paginas else {}

    all_trackers = prowlarr_results + tracker_results
    seen_hashes = set()
    unique_trackers = []
    for t in all_trackers:
        magnet = t.get("magnet", "")
        hash_match = re.search(r"urn:btih:([a-zA-Z0-9]+)", magnet, re.IGNORECASE)
        h = hash_match.group(1).lower() if hash_match else magnet
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_trackers.append(t)

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

    if unique_trackers or ia_data or all_reproductores:
        save_to_cache(query, resultado_final)

    return resultado_final, False

# ==============================================================================
# TELEGRAM HANDLERS & COMANDOS
# ==============================================================================
@new_task
async def buscar(client, message: Message):
    text = message.text.strip().split(" ", 1)
    if len(text) < 2:
        await send_message(
            message,
            "🔍 <b>Uso del comando:</b> <code>/buscar [nombre de película o serie]</code>\n"
            "<i>Ejemplo:</i> <code>/buscar Avatar 2 1080p</code> o <code>/buscar Demon Slayer Capitulo 1</code>"
        )
        return

    query = text[1].strip()
    status_msg = await send_message(
        message,
        f"🤖 <b>Rastreando con IA, TMDb y Prowlarr:</b> <i>'{query}'</i>..."
    )

    try:
        resultado, was_cached = await sync_to_async(procesar_busqueda_universal, query)
        user_id = message.from_user.id if message.from_user else 0
        session_id = f"{user_id}_{int(os.urandom(4).hex(), 16)}"
        SEARCH_SESSION_CACHE[session_id] = resultado

        # Construir Texto
        titulo = resultado.get("titulo", query)
        calidad = resultado.get("calidad", "Multi-Calidad")
        idioma = resultado.get("idioma", "Varios")
        trackers = resultado.get("opciones_trackers", [])
        reproductores = resultado.get("reproductores_online", [])
        directas = resultado.get("descargas_directas", [])
        tmdb = resultado.get("tmdb_info")

        caption = f"🎬 <b>{titulo}</b>\n"
        if calidad:
            caption += f"📊 <b>Calidad:</b> <code>{calidad}</code>\n"
        if idioma:
            caption += f"🌐 <b>Audio/Idioma:</b> <code>{idioma}</code>\n"

        if tmdb and tmdb.get("sinopsis"):
            caption += f"\n📖 <b>Sinopsis:</b>\n<i>{tmdb['sinopsis']}</i>\n"

        caption += f"\n📦 <b>Opciones encontradas:</b>\n"
        caption += f"• 🧲 Torrents / Magnets: <b>{len(trackers)}</b>\n"
        caption += f"• 📹 Streaming / Videos: <b>{len(reproductores)}</b>\n"
        caption += f"• 🌐 Descargas Directas: <b>{len(directas)}</b>\n"

        caption += Config.WATERMARK_FOOTER

        # Construir Botones Interactivos
        buttons = ButtonMaker()

        # Botones de Torrents
        for idx, t in enumerate(trackers[:5]):
            btn_text = f"🧲 [{t.get('peso', 'N/A')}] {t.get('nombre', 'Torrent')[:25]}"
            buttons.data_button(btn_text, f"b_dl_qbt:{session_id}:{idx}")

        # Botones de Videos / Direct
        for idx, v in enumerate(reproductores[:3]):
            btn_text = f"🚀 {v.get('servidor', 'Video')} - {v.get('nombre', 'Ver')[:20]}"
            buttons.data_button(btn_text, f"b_dl_yt:{session_id}:{idx}")

        for idx, d in enumerate(directas[:3]):
            btn_text = f"📥 {d.get('servidor', 'DDL')} ({d.get('calidad', 'HD')})"
            buttons.data_button(btn_text, f"b_dl_ddl:{session_id}:{idx}")

        buttons.data_button("❌ Cerrar", f"b_close:{user_id}")
        reply_markup = buttons.build_menu(1)

        poster_url = resultado.get("poster_url")
        if poster_url:
            try:
                await delete_message(status_msg)
                await message.reply_photo(
                    photo=poster_url,
                    caption=caption,
                    reply_markup=reply_markup
                )
                return
            except Exception as e:
                LOGGER.debug(f"Error enviando foto poster: {e}")

        await edit_message(status_msg, caption, reply_markup)

    except Exception as e:
        LOGGER.error(f"Error procesando búsqueda: {e}")
        await edit_message(status_msg, f"❌ <b>Error al buscar:</b> <code>{str(e)}</code>")

@new_task
async def ai_search_callback(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id

    if data.startswith("b_close"):
        target_user = int(data.split(":")[1])
        if user_id != target_user and user_id != Config.OWNER_ID:
            await query.answer("⛔ Este panel no te pertenece.", show_alert=True)
            return
        await delete_message(query.message)
        return

    parts = data.split(":")
    action = parts[0]
    session_id = parts[1]
    idx = int(parts[2])

    resultado = SEARCH_SESSION_CACHE.get(session_id)
    if not resultado:
        await query.answer("⚠️ La sesión de búsqueda ha expirado. Realiza una nueva búsqueda.", show_alert=True)
        return

    if action == "b_dl_qbt":
        trackers = resultado.get("opciones_trackers", [])
        if idx >= len(trackers):
            await query.answer("Torrent no disponible.", show_alert=True)
            return
        torrent_item = trackers[idx]
        magnet = torrent_item.get("magnet")
        name = torrent_item.get("nombre", "Torrent")

        await query.answer(f"Iniciando descarga Leech: {name[:30]}...", show_alert=False)
        cmd_msg = await query.message.reply_text(
            f"🧲 <b>Iniciando Leech Torrent:</b> <code>{name}</code>\n"
            f"<i>Enviando a qBittorrent...</i>"
        )
        cmd_msg.text = f"/qbleech {magnet}"
        cmd_msg.from_user = query.from_user

        mirror_task = Mirror(client, cmd_msg, is_qbit=True, is_leech=True)
        bot_loop.create_task(mirror_task.new_event())

    elif action == "b_dl_yt":
        reproductores = resultado.get("reproductores_online", [])
        if idx >= len(reproductores):
            await query.answer("Video no disponible.", show_alert=True)
            return
        video_item = reproductores[idx]
        url = video_item.get("url")
        name = video_item.get("nombre", "Video")

        await query.answer(f"Iniciando Leech Video: {name[:30]}...", show_alert=False)
        cmd_msg = await query.message.reply_text(
            f"🚀 <b>Iniciando Selector de Formatos y Calidad:</b> <code>{name}</code>\n"
            f"<i>Extrayendo calidades disponibles (Video / Audio)...</i>"
        )
        cmd_msg.text = f"/ytdlleech -s {url}"
        cmd_msg.from_user = query.from_user

        from .ytdlp import YtDlp
        ytdl_task = YtDlp(client, cmd_msg, is_leech=True)
        bot_loop.create_task(ytdl_task.new_event())

    elif action == "b_dl_ddl":
        directas = resultado.get("descargas_directas", [])
        if idx >= len(directas):
            await query.answer("Enlace no disponible.", show_alert=True)
            return
        ddl_item = directas[idx]
        url = ddl_item.get("url")
        name = ddl_item.get("servidor", "Descarga Directa")

        await query.answer(f"Iniciando Leech Directo: {name}...", show_alert=False)
        cmd_msg = await query.message.reply_text(
            f"📥 <b>Iniciando Leech Directo:</b> <code>{name}</code>\n"
            f"<i>Descargando y subiendo a Telegram...</i>"
        )
        cmd_msg.text = f"/leech {url}"
        cmd_msg.from_user = query.from_user

        mirror_task = Mirror(client, cmd_msg, is_leech=True)
        bot_loop.create_task(mirror_task.new_event())
