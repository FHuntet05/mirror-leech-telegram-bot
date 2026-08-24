from pyrogram.filters import create

from ... import user_data, auth_chats, sudo_users
from ...core.config_manager import Config


class CustomFilters:
    async def owner_filter(self, _, update):
        user = getattr(update, "from_user", None) or getattr(update, "sender_chat", None)
        return bool(user and user.id == Config.OWNER_ID)

    owner = create(owner_filter)

    async def authorized_user(self, _, update):
        user = getattr(update, "from_user", None) or getattr(update, "sender_chat", None)
        if not user:
            return False
        uid = user.id
        msg = getattr(update, "message", update)
        chat = getattr(msg, "chat", None) or getattr(update, "chat", None)
        chat_id = chat.id if chat else 0
        is_topic = getattr(msg, "topic_message", False)
        thread_id = getattr(msg, "message_thread_id", None) if is_topic else None
        return bool(
            uid == Config.OWNER_ID
            or (
                uid in user_data
                and (
                    user_data[uid].get("AUTH", False)
                    or user_data[uid].get("SUDO", False)
                )
            )
            or (
                chat_id in user_data
                and user_data[chat_id].get("AUTH", False)
                and (
                    thread_id is None
                    or thread_id in user_data[chat_id].get("thread_ids", [])
                )
            )
            or uid in sudo_users
            or uid in auth_chats
            or chat_id in auth_chats
            and (
                auth_chats[chat_id]
                and thread_id
                and thread_id in auth_chats[chat_id]
                or not auth_chats[chat_id]
            )
        )

    authorized = create(authorized_user)

    async def sudo_user(self, _, update):
        user = getattr(update, "from_user", None) or getattr(update, "sender_chat", None)
        if not user:
            return False
        uid = user.id
        return bool(
            uid == Config.OWNER_ID
            or uid in user_data
            and user_data[uid].get("SUDO")
            or uid in sudo_users
        )

    sudo = create(sudo_user)
