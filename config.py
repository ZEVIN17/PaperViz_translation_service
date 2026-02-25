"""
PaperViz Translation Service — 配置模块
所有设置从环境变量加载。

环境文件加载规则:
1. 根据 APP_ENV 环境变量决定加载 .env.development 或 .env.production
2. 如果 APP_ENV 未设置，默认为 development
3. 搜索路径：当前目录 → 项目根目录
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ── 确定当前环境 ────────────────────────────────────────
APP_ENV = os.getenv("APP_ENV", "development")

# ── 解析 .env 文件路径 ─────────────────────────────────
_this_dir = Path(__file__).resolve().parent
_project_root = _this_dir.parent

# 根据 APP_ENV 确定要加载的 .env 文件名
_env_filename = f".env.{APP_ENV}"

# 搜索路径（按优先级）
_search_dirs = [_this_dir, _project_root]
_loaded = False

for _base in _search_dirs:
    _env_file = _base / _env_filename
    if _env_file.is_file():
        load_dotenv(_env_file, override=True)
        _loaded = True
        print(f"[Translation Service] 已加载环境文件: {_env_file} (APP_ENV={APP_ENV})")
        break

# 兜底：尝试加载 .env 和 .env.local
if not _loaded:
    for _base in _search_dirs:
        _env_file = _base / ".env"
        _env_local = _base / ".env.local"
        if _env_file.is_file():
            load_dotenv(_env_file, override=True)
            _loaded = True
        if _env_local.is_file():
            load_dotenv(_env_local, override=True)
            _loaded = True

if not _loaded:
    load_dotenv()
    print("[Translation Service] 警告: 未找到任何 .env 文件，使用系统环境变量", file=sys.stderr)

# ── Supabase ──────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# ── Cloudflare R2 (S3-Compatible Storage) ─────────────────
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "paperviz")
# SSRF 防护：允许下载的域名白名单（逗号分隔）
# 例如: "r2.cloudflarestorage.com,your-bucket.s3.amazonaws.com"
R2_ALLOWED_DOMAINS = os.getenv("R2_ALLOWED_DOMAINS", "")

# ── PDFMathTranslate-next 2.0 (in-process via Python API) ─
# 引擎类型: "qwenmt" (DashScope MT) 或 "openai" (OpenAI 兼容)
PDF2ZH_ENGINE = os.getenv("PDF2ZH_ENGINE", "qwenmt")

# ── Celery (Redis Broker) ────────────────────────────────
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# ── 翻译限制 ────────────────────────────────────────────
TRANSLATE_MAX_FILE_SIZE = int(os.getenv("TRANSLATE_MAX_FILE_SIZE", str(50 * 1024 * 1024)))
TRANSLATE_MAX_PAGES = int(os.getenv("TRANSLATE_MAX_PAGES", "100"))
TRANSLATE_TASK_TIMEOUT = int(os.getenv("TRANSLATE_TASK_TIMEOUT", "1800"))

# ── AI - 翻译功能（DashScope API）────────────────────────
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
LLM_TRANSLATE_MODEL = os.getenv("LLM_TRANSLATE_MODEL", "qwen-flash")

# ── 内部 API 鉴权 ────────────────────────────────────────
# 用于微服务间安全通信的内部密钥，部署时必须在环境变量中设置
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
