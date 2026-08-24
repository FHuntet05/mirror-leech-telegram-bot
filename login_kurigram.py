"""
Generador de String Session para Kurigram / Pyrogram (Telegram Premium 4GB)
Autor: Antigravity AI
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Asegurar loop para Python 3.12+ / 3.14
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from pyrogram import Client

API_ID = int(os.getenv("TELEGRAM_API_ID", "31956770"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "6f8f53e5da84ba600ff65dbc805a0e32")

async def main():
    print("=" * 60)
    print("🔐 GENERADOR DE SESIÓN KURIGRAM (MTPROTO ULTRA RÁPIDO - 4GB)")
    print("=" * 60)
    print(f"API_ID: {API_ID}")
    print("Ingresa tu número de teléfono cuando se te solicite.")
    print("=" * 60)

    async with Client(
        name="kurigram_auth",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True
    ) as app:
        me = await app.get_me()
        session_str = await app.export_session_string()

        print("\n" + "=" * 60)
        print("✅ ¡SESIÓN GENERADA CON ÉXITO!")
        print(f"👤 Nombre: {me.first_name}")
        print(f"🆔 ID de Usuario: {me.id}")
        print(f"💎 Es Telegram Premium: {me.is_premium}")
        print("=" * 60)
        print("\n🔑 TU STRING SESSION (Copia y pega esto en tu archivo .env como KURIGRAM_STRING_SESSION):\n")
        print(session_str)
        print("\n" + "=" * 60)

        with open("kurigram_session.txt", "w", encoding="utf-8") as f:
            f.write(session_str)
        print("📁 Guardado también en 'kurigram_session.txt'")

if __name__ == "__main__":
    loop.run_until_complete(main())
