# ⚡ SCRAPPER-FEFT + Mirror-Leech Telegram Bot

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python" alt="Python Version">
  <img src="https://img.shields.io/badge/Telegram-Kurigram%20%2F%20Pyrogram-blue?style=for-the-badge&logo=telegram" alt="Telegram MTProto">
  <img src="https://img.shields.io/badge/Leech%20Limit-4GB%20(Premium)-success?style=for-the-badge" alt="4GB Leech">
  <img src="https://img.shields.io/badge/AI%20Engine-TMDb%20%2B%20Prowlarr%20%2B%20OpenRouter-orange?style=for-the-badge" alt="AI Scraper">
  <img src="https://img.shields.io/badge/Deployment-Coolify%20%2F%20Docker-brightgreen?style=for-the-badge&logo=docker" alt="Coolify Ready">
</p>

Sistema avanzado unificado de **Mirror & Leech a Telegram y Nube** con **Motor de Búsqueda Inteligente con IA**. Integra descarga de Torrents de alta velocidad (qBittorrent / Aria2c), Usenet (SABnzbd), gestores de descarga directa (JDownloader / yt-dlp), selector web de archivos (`/app/files`) y subida ultra-rápida de hasta **4 GB por archivo** a canales de almacenamiento con auto-limpieza de disco en tiempo real.

---

## 🌟 Características Principales

### 🧠 1. Motor de Búsqueda Inteligente con IA (`/buscar` o `/b`)
- **Resolución TMDb:** Identifica títulos de series y películas en español e inglés, resuelve temporadas/episodios (ej. `Capítulo 5` $\rightarrow$ `S01E05`) y genera carátulas HD y sinopsis oficiales.
- **Prowlarr Torznab Multi-Indexer:** Consulta en paralelo todos los indexers configurados en tu servidor Prowlarr (The Pirate Bay, showRSS, YTS, etc.).
- **Trackers Públicos Fallback (ApiBay):** Búsqueda directa deduplicada por `info_hash` en trackers globales si Prowlarr no tiene fuentes.
- **Descubrimiento de Video Streaming (yt-dlp + Dailymotion):** Rastreo de episodios completos (>15 min) y películas con extracción de enlaces directos.
- **Extracción Web con IA (OpenRouter LLM + DuckDuckGo):** Modelos de IA (`google/gemini-2.5-flash-lite`, `meta-llama/llama-3.3-70b-instruct`) que scrapean páginas web y extraen enlaces limpios de descarga directa (Mega, 1fichier, Drive, Mediafire).
- **Botones Interactivos de 1-Click:** Descarga directa de cualquier resultado pulsando los botones interactivos de qBittorrent o yt-dlp.

---

### ⚡ 2. Motor Leech MTProto de 4 GB (Telegram Premium)
- **Autoconversión de Sesión:** Soporta tanto `USER_SESSION_STRING` como `TELETHON_STRING_SESSION` con conversión transparente en memoria.
- **Corte de Video Limpio (FFmpeg):** Para archivos que superan los 3.95 GB, divide videos por keyframes (`.part001.mkv`, `.part002.mkv`) en **videos 100% reproducibles sin necesidad de descomprimir**.
- **Compresión 7-Zip Multivolumen:** Si se usa la opción `-z`, empaqueta en volúmenes estándar (`.zip.001`, `.zip.002`) reconocidos sin error por WinRAR y 7-Zip.
- **Ahorro Estricto de Almacenamiento:** Cada parte subida a Telegram es **borrada inmediatamente del disco local** para evitar saturar el VPS.
- **Inyección de Cookies Anti-Bloqueo:** Carga automática de `YOUTUBE_COOKIES_BASE64` y `FACEBOOK_COOKIES_BASE64` en `cookies.txt` para descargar en 1080p/4K saltando BotGuard.

---

### 🌐 3. Servidor Web FastAPI & Selector de Archivos
- **Dashboard y Health Check:** Endpoint `GET /health` y `GET /` optimizado para monitoreo y comprobación de estado en Coolify y Docker.
- **Selector Web de Archivos (`/app/files`):** Interfaz web interactiva para pausar, reanudar, renombrar o seleccionar archivos específicos de un torrent antes o durante la descarga.

---

### ☁️ 4. Ecosistema Completo de Mirror & Leech
- **qBittorrent:** Control total de WebUI, gestión de prioridades, límites de subida/bajada y gestión de trackers.
- **Aria2c:** Descarga multi-hilo de enlaces HTTP(S), FTP, magnets y torrents.
- **SABnzbd:** Soporte de Usenet (.nzb) con gestión de servidores y passwords.
- **Rclone / Google Drive:** Subida directa o clonado server-side a Google Drive, OneDrive, Mega, Dropbox o cualquier almacenamiento compatible con Rclone.
- **JDownloader & Gallery-dl:** Descarga desde cientos de hosters y galerías de imágenes.

---

## 📋 Lista de Comandos (@BotFather)

Copia y pega la siguiente lista en **@BotFather** mediante `/setcommands` para configurar el menú de tu bot:

```text
buscar - Búsqueda inteligente con IA (TMDb, Prowlarr, Trackers y DDL)
b - Búsqueda rápida con IA
leech - Descarga enlace/magnet y sube a Telegram (Aria2c)
l - Leech rápido con Aria2c
qbleech - Descarga torrent/magnet y sube a Telegram (qBittorrent)
ql - Leech rápido con qBittorrent
ytdlleech - Descarga video/audio con yt-dlp y sube a Telegram
yl - Leech rápido con yt-dlp
sel - Abrir selector web de archivos del torrent
mirror - Descarga enlace y sube a Rclone / GDrive
m - Mirror rápido con Aria2c
qbmirror - Torrent a Rclone / GDrive (qBittorrent)
qm - Mirror rápido con qBittorrent
ytdl - Video a Rclone / GDrive (yt-dlp)
y - Ytdl rápido a la nube
status - Ver panel de descargas y subidas en tiempo real
cancel - Cancelar una tarea activa mediante su ID
cancelall - Cancelar todas las descargas y subidas en curso
forcestart - Forzar inicio de tareas en cola
list - Buscar archivos en tu almacenamiento en la nube
search - Buscar torrents con los plugins de búsqueda
stats - Ver uso de CPU, RAM, disco y velocidad del VPS
ping - Medir latencia de respuesta del bot
bsetting - Configurar ajustes globales del bot (Admin)
usetting - Ajustar tus preferencias personales de subida
restart - Reiniciar servicios y recargar configuraciones
help - Guía completa de uso y comandos adicionales
```

---

## ⚙️ Variables de Entorno (Configuración para Coolify / `.env`)

| Variable | Descripción | Ejemplo / Valor |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` / `BOT_TOKEN` | Token del bot creado con @BotFather | `8009233642:AAE_...` |
| `ADMIN_USER_ID` / `OWNER_ID` | Tu ID numérico de Telegram | `1601545124` |
| `TELEGRAM_API_ID` / `TELEGRAM_API` | API ID de my.telegram.org | `31956770` |
| `TELEGRAM_API_HASH` / `TELEGRAM_HASH`| API Hash de my.telegram.org | `6f8f53e5da84...` |
| `TELETHON_STRING_SESSION` / `USER_SESSION_STRING` | StringSession para subidas 4GB Premium | `1AZWarzQ...` |
| `STORAGE_CHANNEL_ID` / `LEECH_DUMP_CHAT` | Canal de almacenamiento de archivos | `-1003732487046` |
| `OPENROUTER_API_KEY` | API Key de OpenRouter para IA | `sk-or-v1-...` |
| `TMDB_API_KEY` | API Key de The Movie Database (TMDb) | `9cad1b90...` |
| `PROWLARR_URL` | URL de tu servidor Prowlarr | `http://102.129.137.243:9696` |
| `PROWLARR_API_KEY` | API Key de tu Prowlarr | `5cb6fece8a...` |
| `YOUTUBE_COOKIES_BASE64` | Cookies en Base64 de YouTube (Netscape) | `IyBOZXRz...` |
| `FACEBOOK_COOKIES_BASE64` | Cookies en Base64 de Facebook | `IyBOZXRz...` |
| `BASE_URL` | Dominio o IP pública del bot para Web UI | `http://tu-dominio.com` |
| `BASE_URL_PORT` | Puerto HTTP para el servidor FastAPI | `80` |

---

## 🚀 Despliegue Rápido en Coolify

1. **Crear Aplicación:** En Coolify, crea un nuevo recurso seleccionando **Private/Public Git Repository**.
2. **Repositorio:** `https://github.com/FHuntet05/mirror-leech-telegram-bot`
3. **Rama (Branch):** `master`
4. **Build Pack:** `Dockerfile`
5. **Configuración de Red / Puertos:** Mapea el puerto `80` a tu dominio asignado.
6. **Variables de Entorno:** Añade las variables de la tabla anterior en la sección **Environment Variables**.
7. **Desplegar:** Pulsa **Deploy**. Coolify construirá la imagen con Aria2c, qBittorrent, FFmpeg y lanzará el bot con `start.sh`.

---

## 👥 Créditos & Agradecimientos
- **Desarrollador / Maintainer:** [@feft05](https://t.me/feft05)
- **Canal Oficial:** [@fh_estrenos](https://t.me/fh_estrenos)
- Basado en el proyecto original [Mirror-Leech-Telegram-Bot](https://github.com/anasty17/mirror-leech-telegram-bot) de Anas.
