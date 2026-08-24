"""
Generador de Sesión para UserBot Telegram Premium (4GB Uploads)
"""

import asyncio
from telethon import TelegramClient

API_ID = 31956770
API_HASH = "6f8f53e5da84ba600ff65dbc805a0e32"
SESSION_NAME = "userbot_session"

async def main():
    print("==================================================")
    print("🔐 INICIANDO AUTENTICACIÓN TELEGRAM PREMIUM USERBOT")
    print("==================================================")
    print(f"App ID: {API_ID}")
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    
    me = await client.get_me()
    print("\n✅ ¡SESIÓN GENERADA CON ÉXITO!")
    print(f"👤 Nombre: {me.first_name}")
    print(f"🆔 ID: {me.id}")
    print(f"💎 Es Premium: {me.premium}")
    print(f"📁 Archivo de sesión guardado como: {SESSION_NAME}.session")
    print("==================================================")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
