"""
Módulo de Búsqueda y Descarga de Subtítulos (OpenSubtitles REST API v1)
Permite buscar subtítulos oficiales en español, inglés y otros idiomas y recibirlos directamente en Telegram.
"""

import os
import requests
from urllib.parse import quote_plus
from pyrogram.types import Message, CallbackQuery

from .. import LOGGER, bot_loop
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task, sync_to_async
from ..helper.telegram_helper.message_utils import send_message, edit_message, delete_message
from ..helper.telegram_helper.button_build import ButtonMaker

OPENSUBTITLES_CACHE = {}


def buscar_opensubtitles(query: str, lang: str = "es,en", limit: int = 5):
    api_key = Config.OPENSUBTITLES_API_KEY or "fymabHXT9I9uT8lgGjYHSBnCRzzLienO"
    if not api_key:
        return []

    url = f"https://api.opensubtitles.com/api/v1/subtitles?query={quote_plus(query)}&languages={lang}&order_by=ratings"
    headers = {
        "Api-Key": api_key,
        "User-Agent": "SCRAPPER-FEFT v1.0",
        "Content-Type": "application/json"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            LOGGER.warning(f"OpenSubtitles search status: {r.status_code} - {r.text[:100]}")
            return []

        data = r.json().get("data", [])
        results = []
        for item in data[:limit]:
            attrs = item.get("attributes", {})
            files = attrs.get("files", [])
            if not files:
                continue

            file_id = files[0].get("file_id")
            file_name = files[0].get("file_name", "subtitulo.srt")
            language = attrs.get("language", "es")
            release = attrs.get("release", query)
            downloads = attrs.get("download_count", 0)
            ratings = attrs.get("ratings", 0)

            lang_flag = "🇪🇸" if language in ["es", "es-MX", "es-ES"] else "🇬🇧" if language == "en" else "🌐"

            results.append({
                "file_id": file_id,
                "file_name": file_name,
                "language": language,
                "lang_flag": lang_flag,
                "release": release[:50],
                "downloads": downloads,
                "rating": ratings
            })
        return results
    except Exception as e:
        LOGGER.error(f"Error en OpenSubtitles: {e}")
        return []


def descargar_subtitulo_opensubtitles(file_id: int, target_name: str = "subtitulo.srt"):
    api_key = Config.OPENSUBTITLES_API_KEY or "fymabHXT9I9uT8lgGjYHSBnCRzzLienO"
    url = "https://api.opensubtitles.com/api/v1/download"
    headers = {
        "Api-Key": api_key,
        "User-Agent": "SCRAPPER-FEFT v1.0",
        "Content-Type": "application/json"
    }

    try:
        r = requests.post(url, headers=headers, json={"file_id": file_id}, timeout=10)
        if r.status_code != 200:
            return None

        dl_link = r.json().get("link")
        if not dl_link:
            return None

        sub_resp = requests.get(dl_link, timeout=10)
        if sub_resp.status_code == 200:
            out_path = os.path.join(os.getcwd(), target_name)
            with open(out_path, "wb") as f:
                f.write(sub_resp.content)
            return out_path
    except Exception as e:
        LOGGER.error(f"Error descargando subtítulo {file_id}: {e}")
    return None


@new_task
async def search_subtitles(client, message: Message):
    text = message.text.strip().split(" ", 1)
    if len(text) < 2:
        await send_message(
            message,
            "💬 <b>Uso del comando:</b> <code>/subtitulos [nombre de película o serie]</code>\n"
            "<i>Ejemplo:</i> <code>/subtitulos Breaking Bad S01E01</code> o <code>/sub Avatar 2 es</code>"
        )
        return

    raw_query = text[1].strip()
    lang = "es,en"
    if raw_query.lower().endswith(" es"):
        lang = "es"
        query = raw_query[:-3].strip()
    elif raw_query.lower().endswith(" en"):
        lang = "en"
        query = raw_query[:-3].strip()
    else:
        query = raw_query

    status_msg = await send_message(
        message,
        f"🔎 <b>Buscando subtítulos en OpenSubtitles:</b> <i>'{query}'</i>..."
    )

    results = await sync_to_async(buscar_opensubtitles, query, lang)
    if not results:
        await edit_message(
            status_msg,
            f"❌ No se encontraron subtítulos para: <code>{query}</code>\n"
            "<i>Intenta buscar con el nombre en inglés o especificando la temporada/episodio (ej: S01E01).</i>"
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    session_id = f"sub_{user_id}_{int(os.urandom(3).hex(), 16)}"
    OPENSUBTITLES_CACHE[session_id] = {
        "query": query,
        "results": results
    }

    caption = f"💬 <b>Subtítulos encontrados para:</b> <code>{query}</code>\n\n"
    buttons = ButtonMaker()

    for idx, sub in enumerate(results):
        flag = sub["lang_flag"]
        lang_code = sub["language"].upper()
        rel = sub["release"]
        caption += f"{idx + 1}. {flag} <b>[{lang_code}]</b> <code>{rel}</code> (⭐ {sub['rating']})\n"
        btn_text = f"📥 Descargar {flag} #{idx + 1} ({lang_code})"
        buttons.data_button(btn_text, f"sub_dl:{session_id}:{idx}")

    buttons.data_button("❌ Cerrar", f"sub_close:{user_id}")
    await edit_message(status_msg, caption, buttons.build_menu(1))


@new_task
async def subtitles_callback(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id

    if data.startswith("sub_close"):
        target_user = int(data.split(":")[1])
        if user_id != target_user and user_id != Config.OWNER_ID:
            await query.answer("⛔ Este panel no te pertenece.", show_alert=True)
            return
        await delete_message(query.message)
        return

    parts = data.split(":")
    session_id = parts[1]
    idx = int(parts[2])

    cached = OPENSUBTITLES_CACHE.get(session_id)
    if not cached:
        await query.answer("⚠️ Sesión expirada. Busca de nuevo con /subtitulos", show_alert=True)
        return

    results = cached.get("results", [])
    if idx >= len(results):
        await query.answer("Subtítulo no disponible.", show_alert=True)
        return

    sub_item = results[idx]
    file_id = sub_item["file_id"]
    lang = sub_item["language"]
    clean_name = f"{cached['query']}_{lang.upper()}.srt".replace(" ", "_").replace("/", "_")

    await query.answer("Descargando archivo .srt...", show_alert=False)
    sub_path = await sync_to_async(descargar_subtitulo_opensubtitles, file_id, clean_name)

    if sub_path and os.path.exists(sub_path):
        try:
            await query.message.reply_document(
                document=sub_path,
                caption=f"💬 <b>Subtítulo:</b> <code>{clean_name}</code>\n"
                        f"🌐 <b>Idioma:</b> {sub_item['lang_flag']} {lang.upper()}\n"
                        f"📦 <b>Release:</b> <code>{sub_item['release']}</code>"
                        f"{Config.WATERMARK_FOOTER}"
            )
            os.remove(sub_path)
        except Exception as e:
            LOGGER.error(f"Error enviando documento subtítulo: {e}")
            await query.message.reply_text(f"❌ Error al enviar el archivo de subtítulo: {e}")
    else:
        await query.message.reply_text("❌ No se pudo descargar el archivo de subtítulo de OpenSubtitles.")
