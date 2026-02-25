"""
PaperViz Translation Service v1.0（独立翻译微服务）
====================================================
独立于主 python_service 的翻译微服务。
所有依赖 pdf2zh_next（AGPL-3.0）的代码集中在本服务中。

FastAPI Web 层接收翻译请求、校验参数、分发 Celery 异步任务，
并提供状态查询/取消接口。

实际翻译工作由 pdf2zh_next 2.0 Python API 在 Celery Worker 进程内执行。

启动:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from celery_app import celery_app
from config import INTERNAL_API_KEY, PDF2ZH_ENGINE
from schemas.translate import (
    CancelResponse,
    TranslateRequest,
    TranslateResponse,
    TranslationStatusResponse,
)
from services.supabase_client import (
    get_translation,
    mark_cancelled,
    upsert_translation,
)
from tasks.translate import translate_paper_task

# ── 日志 ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("translation_service.main")

# ── 限流 ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── 内部 API 鉴权 ─────────────────────────────────────
def verify_internal_token(request: Request) -> bool:
    """
    验证内部 API 密钥。
    
    检查请求头 X-Internal-Token 是否与服务端配置的 INTERNAL_API_KEY 匹配。
    如果未配置 INTERNAL_API_KEY，则跳过验证（仅用于开发环境）。
    """
    if not INTERNAL_API_KEY:
        # 未配置密钥，跳过验证（仅开发环境使用）
        logger.warning("INTERNAL_API_KEY 未配置，已跳过鉴权验证")
        return True
    
    auth_header = request.headers.get("X-Internal-Token")
    if not auth_header:
        return False
    
    return auth_header == INTERNAL_API_KEY


async def require_internal_auth(request: Request, response: Response):
    """内部 API 认证依赖项，用于 FastAPI 路由保护。"""
    if not verify_internal_token(request):
        logger.warning(f"内部 API 鉴权失败: 缺少或无效的 X-Internal-Token 头")
        raise HTTPException(
            status_code=401,
            detail="缺少有效的内部认证凭证"
        )

# ── FastAPI 应用 ─────────────────────────────────────
app = FastAPI(
    title="PaperViz Translation Service",
    version="1.0.0",
    description="独立翻译微服务 — PDF 翻译编排（AGPL-3.0 隔离）",
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "请求过于频繁，请稍后再试。"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 健康检查 ──────────────────────────────────────────

@app.get("/health")
async def health():
    """服务健康状态 + 依赖检查。"""
    # 检查 pdf2zh_next 是否可导入
    pdf2zh_ok = False
    pdf2zh_version = "unknown"
    try:
        import pdf2zh_next
        pdf2zh_version = getattr(pdf2zh_next, "__version__", "unknown")
        pdf2zh_ok = True
    except ImportError:
        pass

    # 检查 Celery Worker 状态
    celery_ok = False
    try:
        inspector = celery_app.control.inspect(timeout=3)
        workers = inspector.ping()
        celery_ok = bool(workers)
    except Exception:
        pass

    overall = "ok" if (pdf2zh_ok and celery_ok) else "degraded"
    return {
        "status": overall,
        "service": "paperviz-translation",
        "version": "1.0.0",
        "pdf2zh_next": {
            "version": pdf2zh_version,
            "available": pdf2zh_ok,
            "engine": PDF2ZH_ENGINE,
            "mode": "in-process (Python API)",
        },
        "celery": {"healthy": celery_ok},
    }


# ── POST /translate ──────────────────────────────────

@app.post("/translate", response_model=TranslateResponse)
@limiter.limit("5/minute")
async def start_translation(req: TranslateRequest, request: Request, response: Response):
    """提交新翻译任务（或返回已有进度）。"""
    # 内部 API 鉴权
    await require_internal_auth(request, response)
    
    logger.info(
        f"POST /translate — paper_id={req.paper_id}, mode={req.mode}"
    )

    # 检查是否有已有翻译记录
    existing = get_translation(req.paper_id)
    if existing:
        # 检查模式是否一致
        existing_mode = existing.get("translation_mode")
        if existing_mode == req.mode:
            status = existing.get("status", "")
            if status == "completed":
                return TranslateResponse(
                    success=True,
                    paper_id=req.paper_id,
                    message="翻译已完成",
                )
            if status in ("queued", "downloading", "translating", "uploading",
                          "pending", "extracting"):
                return TranslateResponse(
                    success=True,
                    celery_task_id=existing.get("celery_task_id"),
                    paper_id=req.paper_id,
                    message=f"翻译进行中 (状态: {status})",
                )

    # 创建初始数据库记录
    upsert_translation(req.paper_id, {
        "status": "queued",
        "translation_mode": req.mode,
        "translate_engine": "pdf2zh_next",
        "error_message": None,
        "progress_percent": 0,
        "progress_current": 0,
        "progress_total": 0,
        "translated_pdf_url": None,
        "retry_count": 0,
    })

    # 分发 Celery 任务（指定队列）
    task = translate_paper_task.apply_async(
        kwargs={
            "paper_id": req.paper_id,
            "file_url": req.file_url,
            "mode": req.mode,
        },
        queue=req.queue,  # 根据用户层级分发到对应队列
    )

    upsert_translation(req.paper_id, {"celery_task_id": task.id})

    logger.info(f"[{req.paper_id}] Celery task dispatched → {task.id}")
    return TranslateResponse(
        success=True,
        celery_task_id=task.id,
        paper_id=req.paper_id,
        message="翻译任务已提交",
    )


# ── GET /translate/status/{paper_id} ─────────────────

@app.get(
    "/translate/status/{paper_id}",
    response_model=TranslationStatusResponse,
)
async def get_translate_status(paper_id: str, request: Request, response: Response):
    """查询当前翻译状态和进度。"""
    # 内部 API 鉴权
    await require_internal_auth(request, response)
    
    record = get_translation(paper_id)
    if not record:
        return TranslationStatusResponse(
            paper_id=paper_id, status="not_found"
        )

    return TranslationStatusResponse(
        paper_id=paper_id,
        status=record.get("status", "unknown"),
        translation_mode=record.get("translation_mode"),
        progress_percent=record.get("progress_percent", 0),
        progress_current=record.get("progress_current", 0),
        progress_total=record.get("progress_total", 0),
        translated_pdf_url=record.get("translated_pdf_url"),
        error_message=record.get("error_message"),
        celery_task_id=record.get("celery_task_id"),
        translate_engine=record.get("translate_engine"),
        retry_count=record.get("retry_count", 0),
        started_at=record.get("started_at"),
        completed_at=record.get("completed_at"),
    )


# ── POST /translate/cancel/{paper_id} ────────────────

@app.post(
    "/translate/cancel/{paper_id}",
    response_model=CancelResponse,
)
async def cancel_translation(paper_id: str, request: Request, response: Response):
    """取消进行中的翻译任务。"""
    # 内部 API 鉴权
    await require_internal_auth(request, response)
    
    record = get_translation(paper_id)
    if not record:
        raise HTTPException(status_code=404, detail="翻译记录不存在")

    status = record.get("status", "")
    if status in ("completed", "failed", "cancelled"):
        return CancelResponse(
            success=False,
            message=f"无法取消: 当前状态为 {status}",
        )

    # 撤销 Celery 任务
    celery_task_id = record.get("celery_task_id")
    if celery_task_id:
        celery_app.control.revoke(celery_task_id, terminate=True)
        logger.info(f"[{paper_id}] Celery task {celery_task_id} revoked")

    mark_cancelled(paper_id)
    return CancelResponse(success=True, message="翻译任务已取消")


# ── 兼容旧接口 ───────────────────────────────────────

@app.post("/parse_pdf")
async def parse_pdf_legacy(request: Request, response: Response):
    """保留的旧接口，向后兼容。"""
    # 内部 API 鉴权
    await require_internal_auth(request, response)
    
    body = await request.json()
    req = TranslateRequest(
        paper_id=body.get("paper_id", ""),
        file_url=body.get("file_url", ""),
    )
    return await start_translation(req, request)


# ── 入口点 ────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Translation Service v1.0 starting on :{port}")
    logger.info(f"  pdf2zh engine : {PDF2ZH_ENGINE}")
    uvicorn.run(app, host="0.0.0.0", port=port)
