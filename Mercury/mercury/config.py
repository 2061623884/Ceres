"""读取 Mercury/.env；不依赖当前工作目录。"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# override=False：已存在的环境变量（如测试中 monkeypatch 的值）不会被 .env 覆盖
load_dotenv(PROJECT_ROOT / ".env", override=False)


def db_path() -> Path:
    """每次调用时读取 MERCURY_DB_PATH，相对路径按 PROJECT_ROOT 解析。"""
    path = Path(os.getenv("MERCURY_DB_PATH") or "data/mercury.db")
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def llm_settings() -> dict:
    """每次调用时读取 LLM 配置。"""
    return {
        "base_url": os.getenv("OPENAI_BASE_URL"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model": os.getenv("LLM_MODEL"),
    }
