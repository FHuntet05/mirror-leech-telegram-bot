from importlib import import_module
from ast import literal_eval
from os import getenv
import base64
import os
import struct

from bot import LOGGER


def convert_telethon_to_pyrogram_session(telethon_str: str, api_id: int, user_id: int = 0) -> str:
    if not telethon_str:
        return ""
    try:
        from telethon.sessions import StringSession
        s = StringSession(telethon_str)
        if not s.auth_key or not s.auth_key.key:
            return ""
        packed = struct.pack(
            ">BI?256sQ?",
            s.dc_id,
            int(api_id),
            False,
            s.auth_key.key,
            int(user_id) if user_id else 0,
            False
        )
        return base64.urlsafe_b64encode(packed).decode().rstrip("=")
    except Exception as e:
        LOGGER.warning(f"Failed to autoconvert Telethon session: {e}")
        return ""


def setup_global_cookies():
    all_cookies = ["# Netscape HTTP Cookie File\n# Multi-platform Cookies Engine\n"]
    for var_name in ["GLOBAL_COOKIES_BASE64", "YOUTUBE_COOKIES_BASE64", "FACEBOOK_COOKIES_BASE64", "INSTAGRAM_COOKIES_BASE64"]:
        b64_env = getenv(var_name, "").strip()
        if b64_env:
            try:
                decoded = base64.b64decode(b64_env).decode('utf-8', errors='ignore')
                all_cookies.append(decoded)
                LOGGER.info(f"Loaded cookies from {var_name} ({len(decoded)} bytes)")
            except Exception as e:
                LOGGER.error(f"Error decoding {var_name}: {e}")
    for var_name in ["GLOBAL_COOKIES_TEXT", "YOUTUBE_COOKIES_TEXT", "FACEBOOK_COOKIES_TEXT"]:
        txt_env = getenv(var_name, "").strip()
        if txt_env:
            all_cookies.append(txt_env)
    if len(all_cookies) > 1:
        for path in ["cookies.txt", "/app/cookies.txt"]:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(all_cookies))
                LOGGER.info(f"Cookies saved to {path}")
            except Exception:
                pass


class Config:
    ALLDEBRID_API_KEY = ""
    TORBOX_API_KEY = ""
    AS_DOCUMENT = False
    AUTHORIZED_CHATS = ""
    BASE_URL = ""
    BASE_URL_PORT = 80
    BOT_TOKEN = ""
    BUZZHEAVIER_ACCOUNT_ID = ""
    BUZZHEAVIER_FOLDER_ID = ""
    GOFILE_API_KEY = ""
    TLDV_TOKEN = ""
    CMD_SUFFIX = ""
    CLONE_DUMP_CHATS = ""
    DATABASE_URL = ""
    DATABASE_NAME = "mltb"
    DEFAULT_UPLOAD = "rc"
    EQUAL_SPLITS = False
    EXCLUDED_EXTENSIONS = ""
    INCLUDED_EXTENSIONS = ""
    FFMPEG_CMDS = {}
    FILELION_API = ""
    FILES_LINKS = False
    GALLERY_DL_OPTIONS = {}
    GDRIVE_ID = ""
    INCOMPLETE_TASK_NOTIFIER = False
    INDEX_URL = ""
    IS_TEAM_DRIVE = False
    JD_EMAIL = ""
    JD_PASS = ""
    LEECH_DUMP_CHAT = ""
    LEECH_FILENAME_PREFIX = ""
    LEECH_SPLIT_SIZE = 2097152000
    MEDIA_GROUP = False
    HYBRID_LEECH = False
    HYDRA_IP = ""
    HYDRA_API_KEY = ""
    NAME_SUBSTITUTE = r""
    OWNER_ID = 0
    QUEUE_ALL = 0
    QUEUE_DOWNLOAD = 0
    QUEUE_UPLOAD = 0
    RCLONE_FLAGS = ""
    RCLONE_PATH = ""
    RCLONE_SERVE_URL = ""
    RCLONE_SERVE_USER = ""
    RCLONE_SERVE_PASS = ""
    RCLONE_SERVE_PORT = 8080
    RSS_CHAT = ""
    RSS_DELAY = 600
    RSS_SIZE_LIMIT = 0
    SEARCH_API_LINK = ""
    SEARCH_LIMIT = 0
    SEARCH_PLUGINS = []
    STATUS_LIMIT = 4
    STATUS_UPDATE_INTERVAL = 15
    STOP_DUPLICATE = False
    STREAMWISH_API = ""
    SUDO_USERS = ""
    TELEGRAM_API = 0
    TELEGRAM_HASH = ""
    TG_PROXY = {}
    THUMBNAIL_LAYOUT = ""
    TORRENT_TIMEOUT = 120
    UPLOAD_PATHS = {}
    UPSTREAM_REPO = ""
    UPSTREAM_BRANCH = "master"
    USENET_SERVERS = []
    USER_SESSION_STRING = ""
    USER_TRANSMISSION = False
    USE_SERVICE_ACCOUNTS = False
    WEB_PINCODE = False
    # AI Scraper & Media
    OPENROUTER_API_KEY = ""
    TMDB_API_KEY = ""
    PROWLARR_URL = ""
    PROWLARR_API_KEY = ""
    YOUTUBE_COOKIES_BASE64 = ""
    FACEBOOK_COOKIES_BASE64 = ""
    STORAGE_CHANNEL_ID = 0
    ADMIN_USER_ID = 0
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_API_ID = 0
    TELEGRAM_API_HASH = ""
    TELETHON_STRING_SESSION = ""
    PRIMARY_MODEL = "google/gemini-2.5-flash-lite"
    FALLBACK_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
    DB_PATH = "multimedia_cache.db"
    WATERMARK_FOOTER = "\n\n📢 <b>Canal Oficial:</b> @fh_estrenos\n👤 <b>Admin:</b> @feft05"
    YT_DLP_OPTIONS = {}

    @classmethod
    def _convert(cls, key: str, value):
        if not hasattr(cls, key):
            raise KeyError(f"{key} is not a valid configuration key.")

        expected_type = type(getattr(cls, key))

        if value is None:
            return None

        if isinstance(value, expected_type):
            return value

        if expected_type is bool:
            return str(value).strip().lower() in {"true", "1", "yes"}

        if expected_type in [list, dict]:
            if not isinstance(value, str):
                raise TypeError(
                    f"{key} should be {expected_type.__name__}, got {type(value).__name__}"
                )

            if not value:
                return expected_type()

            try:
                evaluated = literal_eval(value)
                if not isinstance(evaluated, expected_type):
                    raise TypeError(
                        f"Expected {expected_type.__name__}, got {type(evaluated).__name__}"
                    )
                return evaluated
            except (ValueError, SyntaxError, TypeError) as e:
                raise TypeError(
                    f"{key} should be {expected_type.__name__}, got invalid string: {value}"
                ) from e

        try:
            return expected_type(value)
        except (ValueError, TypeError) as exc:
            raise TypeError(
                f"Invalid type for {key}: expected {expected_type}, got {type(value)}"
            ) from exc

    @classmethod
    def get(cls, key: str):
        return getattr(cls, key, None)

    @classmethod
    def set(cls, key: str, value) -> None:
        if not hasattr(cls, key):
            raise KeyError(f"{key} is not a valid configuration key.")

        converted_value = cls._convert(key, value)
        setattr(cls, key, converted_value)

    @classmethod
    def get_all(cls):
        return {
            key: getattr(cls, key)
            for key in cls.__dict__.keys()
            if not key.startswith("__") and not callable(getattr(cls, key))
        }

    @classmethod
    def _is_valid_config_attr(cls, attr: str) -> bool:
        if attr.startswith("__") or callable(getattr(cls, attr, None)):
            return False
        return hasattr(cls, attr)

    @classmethod
    def _process_config_value(cls, attr: str, value):
        if not value:
            return None

        converted_value = cls._convert(attr, value)

        if isinstance(converted_value, str):
            converted_value = converted_value.strip()

        if attr == "DEFAULT_UPLOAD" and converted_value not in {"gd", "bh", "gf"}:
            return "rc"

        if attr in {
            "BASE_URL",
            "RCLONE_SERVE_URL",
            "SEARCH_API_LINK",
        }:
            return converted_value.strip("/") if converted_value else ""

        if attr == "USENET_SERVERS" and (
            not converted_value or not converted_value[0].get("host")
        ):
            return None

        return converted_value

    @classmethod
    def _load_from_module(cls) -> bool:
        try:
            settings = import_module("config")
        except ModuleNotFoundError:
            return False

        for attr in dir(settings):
            if not cls._is_valid_config_attr(attr):
                continue

            raw_value = getattr(settings, attr)
            processed_value = cls._process_config_value(attr, raw_value)

            if processed_value is not None:
                setattr(cls, attr, processed_value)

        return True

    @classmethod
    def _load_from_env(cls) -> None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        # Aliases mapping
        env_aliases = {
            "BOT_TOKEN": ["TELEGRAM_BOT_TOKEN"],
            "OWNER_ID": ["ADMIN_USER_ID"],
            "TELEGRAM_API": ["TELEGRAM_API_ID"],
            "TELEGRAM_HASH": ["TELEGRAM_API_HASH"],
            "LEECH_DUMP_CHAT": ["STORAGE_CHANNEL_ID"],
            "USER_SESSION_STRING": ["PYROGRAM_STRING_SESSION", "KURIGRAM_STRING_SESSION"],
        }

        for attr in dir(cls):
            if not cls._is_valid_config_attr(attr):
                continue

            env_value = getenv(attr)
            if env_value is None and attr in env_aliases:
                for alt in env_aliases[attr]:
                    alt_val = getenv(alt)
                    if alt_val is not None:
                        env_value = alt_val
                        break

            if env_value is None:
                continue

            processed_value = cls._process_config_value(attr, env_value)
            if processed_value is not None:
                setattr(cls, attr, processed_value)

        # Handle Telethon session conversion if USER_SESSION_STRING is missing
        if not cls.USER_SESSION_STRING:
            tele_str = getenv("TELETHON_STRING_SESSION", "").strip()
            if not tele_str:
                if os.path.exists("string_session.txt"):
                    try:
                        with open("string_session.txt", "r", encoding="utf-8") as f:
                            tele_str = f.read().strip()
                    except Exception:
                        pass
            if tele_str and cls.TELEGRAM_API:
                converted = convert_telethon_to_pyrogram_session(
                    tele_str, cls.TELEGRAM_API, cls.OWNER_ID
                )
                if converted:
                    cls.USER_SESSION_STRING = converted
                    cls.USER_TRANSMISSION = True
                    cls.HYBRID_LEECH = True
                    LOGGER.info("Successfully converted Telethon StringSession to Pyrogram session!")

        setup_global_cookies()

    @classmethod
    def _validate_required_config(cls) -> None:
        # Check aliases
        if not cls.BOT_TOKEN and cls.TELEGRAM_BOT_TOKEN:
            cls.BOT_TOKEN = cls.TELEGRAM_BOT_TOKEN
        if not cls.OWNER_ID and cls.ADMIN_USER_ID:
            cls.OWNER_ID = cls.ADMIN_USER_ID
        if not cls.TELEGRAM_API and cls.TELEGRAM_API_ID:
            cls.TELEGRAM_API = cls.TELEGRAM_API_ID
        if not cls.TELEGRAM_HASH and cls.TELEGRAM_API_HASH:
            cls.TELEGRAM_HASH = cls.TELEGRAM_API_HASH
        if not cls.LEECH_DUMP_CHAT and cls.STORAGE_CHANNEL_ID:
            cls.LEECH_DUMP_CHAT = str(cls.STORAGE_CHANNEL_ID)

        required_keys = ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]

        for key in required_keys:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")

    @classmethod
    def load(cls) -> None:
        if not cls._load_from_module():
            LOGGER.info(
                "Config module not found, loading from environment variables..."
            )
            cls._load_from_env()

        cls._validate_required_config()

    @classmethod
    def load_dict(cls, config_dict) -> None:
        for key, value in config_dict.items():
            if not hasattr(cls, key):
                continue

            processed_value = cls._process_config_value(key, value)

            if key == "USENET_SERVERS" and processed_value is None:
                processed_value = []

            if processed_value is not None:
                setattr(cls, key, processed_value)

        cls._validate_required_config()
