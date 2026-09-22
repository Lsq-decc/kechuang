import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent
    _paddle_runtime_home = os.getenv(
        "PADDLE_RUNTIME_HOME", str(BASE_DIR / "instance" / "paddle_runtime")
    )
    if not os.path.isabs(_paddle_runtime_home):
        _paddle_runtime_home = str((BASE_DIR / _paddle_runtime_home).resolve())

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:root@127.0.0.1:3306/kechuang?charset=utf8mb4",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", "50")) * 1024 * 1024
    UPLOAD_FOLDER = str(BASE_DIR / "instance" / "uploads")
    MATERIAL_STORAGE_FOLDER = str(BASE_DIR / "instance" / "materials")
    PADDLE_RUNTIME_HOME = _paddle_runtime_home
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "webp"}
    AUTO_CREATE_DB = os.getenv("AUTO_CREATE_DB", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    OCR_ENGINE = os.getenv("OCR_ENGINE", "paddle").lower()
    AI_PARSER_ENABLED = os.getenv("AI_PARSER_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL = os.getenv(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    ).rstrip("/")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "60"))
    DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "4096"))
    AI_PARSER_MAX_ITEMS = int(os.getenv("AI_PARSER_MAX_ITEMS", "400"))
    VISION_PARSER_ENABLED = os.getenv("VISION_PARSER_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    VISION_API_KEY = os.getenv("VISION_API_KEY", "").strip()
    VISION_BASE_URL = os.getenv(
        "VISION_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).rstrip("/")
    VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-max").strip()
    VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "120"))
    VISION_MAX_TOKENS = int(os.getenv("VISION_MAX_TOKENS", "4096"))
    VISION_MAX_IMAGE_WIDTH = int(os.getenv("VISION_MAX_IMAGE_WIDTH", "2000"))
    CSRF_ENABLED = os.getenv("CSRF_ENABLED", "true").lower() in {"1", "true", "yes"}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() in {"1", "true", "yes"}
    JSON_AS_ASCII = False
