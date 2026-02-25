#!/bin/bash
# ============================================
# PaperViz Translation Service 启动脚本
# 启动前进行环境变量校验和防误连检查
# ============================================

set -e

# 若存在 venv 则优先使用，便于本地开发
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/venv/bin" ]; then
    export PATH="$SCRIPT_DIR/venv/bin:$PATH"
fi

# ── 环境变量校验 ──────────────────────────────────────
echo "=== PaperViz Translation Service 启动检查 ==="

# 设置默认 APP_ENV
export APP_ENV="${APP_ENV:-development}"
echo "当前环境: APP_ENV=$APP_ENV"

# 核心变量校验
MISSING=""
[ -z "$SUPABASE_URL" ] && MISSING="$MISSING SUPABASE_URL"
[ -z "$SUPABASE_SERVICE_ROLE_KEY" ] && MISSING="$MISSING SUPABASE_SERVICE_ROLE_KEY"
[ -z "$R2_ACCOUNT_ID" ] && MISSING="$MISSING R2_ACCOUNT_ID"
[ -z "$R2_ACCESS_KEY_ID" ] && MISSING="$MISSING R2_ACCESS_KEY_ID"
[ -z "$R2_SECRET_ACCESS_KEY" ] && MISSING="$MISSING R2_SECRET_ACCESS_KEY"
[ -z "$DASHSCOPE_API_KEY" ] && MISSING="$MISSING DASHSCOPE_API_KEY"

if [ -n "$MISSING" ]; then
    # config.py 会自动加载 .env 文件，尝试加载后再检查
    echo "部分变量未在系统环境中设置，将由 config.py 从 .env 文件加载"
fi

# ── 防误连生产校验（仅本地开发时生效）──────────────────
if [ "$APP_ENV" = "development" ]; then
    # 如果 SUPABASE_URL 已设置且包含生产项目 ID，则拒绝启动
    PROD_PROJECT_ID="laemhnzpnncwlijljwcy"
    if echo "$SUPABASE_URL" | grep -q "$PROD_PROJECT_ID" 2>/dev/null; then
        echo ""
        echo "=========================================="
        echo "🚫 错误：检测到本地开发正在连接生产环境！"
        echo "   SUPABASE_URL 包含生产项目 ID"
        echo "   请检查 .env.development 配置文件"
        echo "=========================================="
        echo ""
        exit 1
    fi
fi

echo "启动检查通过 ✓"
echo ""

# ── 启动服务 ──────────────────────────────────────────
echo "Starting Celery worker …"
celery -A celery_app worker \
    --loglevel=info \
    --concurrency=2 &
CELERY_PID=$!

echo "Starting FastAPI server …"
uvicorn main:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# 等待任一进程退出（兼容 macOS bash 3.x 和 Linux）
while true; do
    if ! kill -0 $CELERY_PID 2>/dev/null; then
        wait $CELERY_PID 2>/dev/null
        EXIT_CODE=$?
        echo "Celery exited — shutting down …"
        kill $UVICORN_PID 2>/dev/null
        exit ${EXIT_CODE:-1}
    fi
    if ! kill -0 $UVICORN_PID 2>/dev/null; then
        wait $UVICORN_PID 2>/dev/null
        EXIT_CODE=$?
        echo "Uvicorn exited — shutting down …"
        kill $CELERY_PID 2>/dev/null
        exit ${EXIT_CODE:-1}
    fi
    sleep 1
done
