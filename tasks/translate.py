"""
Celery 任务: 通过内部翻译引擎翻译 PDF 论文。

工作流程
--------
1. 从 R2 / URL 下载 PDF
2. 校验文件（MIME 类型、大小 <= 50 MB、页数 <= 100）
3. 调用 pdf2zh_next.do_translate_async_stream（进程内异步）
4. 流式进度事件 -> 同步更新到 Supabase
5. 上传翻译后的 PDF 到 R2
6. 更新 Supabase -> status = completed

重试策略: 对瞬态错误最多自动重试 2 次。
校验失败立即拒绝（不重试）。

⚠️ 本模块 import pdf2zh_next，受 AGPL-3.0 约束。
"""

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF — 仅用于页数校验
from celery import Task
from celery.exceptions import Reject, SoftTimeLimitExceeded

from celery_app import celery_app
from config import TRANSLATE_MAX_FILE_SIZE, TRANSLATE_MAX_PAGES
from exceptions import (
    FileValidationError,
    StorageError,
    TranslationError,
)
from services.pdf2zh_next_config import WORK_DIR, build_settings
from services.r2_storage import download_pdf, upload_pdf
from services.supabase_client import upsert_translation, mark_failed

logger = logging.getLogger("translation_service.tasks.translate")

# 确保工作目录存在
WORK_DIR.mkdir(parents=True, exist_ok=True)
(WORK_DIR / "output").mkdir(parents=True, exist_ok=True)


# ── 文件校验 ──────────────────────────────────────────

def _validate_pdf(pdf_bytes: bytes) -> int:
    """
    校验下载的 PDF。

    返回页数。
    如果无效则抛出 FileValidationError（不可重试）。
    """
    size_mb = len(pdf_bytes) / (1024 * 1024)
    max_mb = TRANSLATE_MAX_FILE_SIZE / (1024 * 1024)
    if len(pdf_bytes) > TRANSLATE_MAX_FILE_SIZE:
        raise FileValidationError(
            f"文件过大: {size_mb:.1f}MB (上限 {max_mb:.0f}MB)"
        )

    if not pdf_bytes[:5] == b"%PDF-":
        raise FileValidationError("不是有效的 PDF 文件")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)
        doc.close()
    except Exception as e:
        raise FileValidationError(f"无法读取 PDF: {e}")

    if page_count == 0:
        raise FileValidationError("PDF 没有页面")
    if page_count > TRANSLATE_MAX_PAGES:
        raise FileValidationError(
            f"页数过多: {page_count} 页 (上限 {TRANSLATE_MAX_PAGES} 页)"
        )

    return page_count


# ── 异步翻译执行器 ───────────────────────────────────

async def _run_translation(
    paper_id: str,
    input_pdf_path: Path,
    mode: str,
    page_count: int,
) -> dict:
    """
    通过异步流式 API 运行 pdf2zh_next 翻译。

    返回包含输出路径的字典: {mono, dual, no_watermark_mono, no_watermark_dual}
    """
    from pdf2zh_next.high_level import do_translate_async_stream

    settings = build_settings(mode=mode)
    output_paths = {}
    last_progress_update = 0

    async for event in do_translate_async_stream(settings, input_pdf_path):
        etype = event.get("type")

        if etype in ("progress_start", "progress_update", "progress_end"):
            overall = event.get("overall_progress", 0)
            stage = event.get("stage", "")
            stage_current = event.get("stage_current", 0)
            stage_total = event.get("stage_total", 0)

            # 节流数据库更新: 仅在进度变化 >= 2% 时写入
            int_progress = int(overall)
            if int_progress - last_progress_update >= 2 or etype == "progress_end":
                last_progress_update = int_progress
                upsert_translation(paper_id, {
                    "progress_percent": int_progress,
                    "progress_current": stage_current,
                    "progress_total": stage_total,
                })
                logger.info(
                    f"[{paper_id}] {stage} — {overall:.1f}% "
                    f"(step {stage_current}/{stage_total})"
                )

        elif etype == "error":
            error_msg = event.get("error", "Unknown error")
            error_type = event.get("error_type", "UnknownError")
            details = event.get("details", "")
            logger.error(
                f"[{paper_id}] Translation service error: {error_type}: {error_msg}"
            )
            if details:
                logger.error(f"[{paper_id}] Details: {details[:500]}")
            # 清洗错误信息供用户查看
            raise TranslationError(f"翻译引擎错误: {error_msg}")

        elif etype == "finish":
            result = event["translate_result"]
            output_paths = {
                "mono": getattr(result, "mono_pdf_path", None),
                "dual": getattr(result, "dual_pdf_path", None),
                "no_watermark_mono": getattr(result, "no_watermark_mono_pdf_path", None),
                "no_watermark_dual": getattr(result, "no_watermark_dual_pdf_path", None),
            }
            total_seconds = getattr(result, "total_seconds", 0)
            logger.info(
                f"[{paper_id}] Translation finished in {total_seconds:.1f}s"
            )
            break

    return output_paths


# ── Celery 任务 ──────────────────────────────────────

@celery_app.task(
    bind=True,
    name="tasks.translate_paper",
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=1800,
    time_limit=2100,
    acks_late=True,
    reject_on_worker_lost=True,
)
def translate_paper_task(
    self: Task,
    paper_id: str,
    file_url: str,
    mode: str = "dual",
) -> dict:
    """
    使用 pdf2zh_next 2.0 Python API 的主翻译流水线。

    Parameters
    ----------
    paper_id : str
        ``papers`` 表中论文的 UUID。
    file_url : str
        指向原始 PDF 的 R2 key 或完整 URL。
    mode : str
        ``"mono"``（仅中文）或 ``"dual"``（中英双语对照）。
    """
    attempt = self.request.retries + 1
    logger.info(
        f"[{paper_id}] Starting translation "
        f"(mode={mode}, attempt={attempt}/{self.max_retries + 1})"
    )

    # 为此任务创建唯一临时目录
    task_dir = Path(tempfile.mkdtemp(prefix=f"pdf2zh_{paper_id[:8]}_"))
    input_pdf_path = task_dir / f"{paper_id}.pdf"

    try:
        # ── 步骤 1: 标记下载中 ─────────────────
        upsert_translation(paper_id, {
            "status": "downloading",
            "celery_task_id": self.request.id,
            "translation_mode": mode,
            "translate_engine": "pdf2zh_next",
            "retry_count": self.request.retries,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "error_message": None,
            "translated_pdf_url": None,
        })

        logger.info(f"[{paper_id}] Downloading PDF …")
        pdf_bytes = download_pdf(file_url)
        logger.info(f"[{paper_id}] Downloaded {len(pdf_bytes)} bytes")

        # ── 步骤 2: 校验 ─────────────────────────
        page_count = _validate_pdf(pdf_bytes)
        logger.info(
            f"[{paper_id}] Validation OK — "
            f"{page_count} pages, {len(pdf_bytes) / 1024 / 1024:.1f} MB"
        )

        # 将输入 PDF 保存到临时文件（pdf2zh_next 需要文件路径）
        input_pdf_path.write_bytes(pdf_bytes)

        upsert_translation(paper_id, {
            "status": "translating",
            "source_file_size": len(pdf_bytes),
            "source_page_count": page_count,
            "progress_total": page_count,
            "progress_current": 0,
            "progress_percent": 0,
            "total_paragraphs": page_count,
            "translated_count": 0,
        })

        # ── 步骤 3+4: 通过 pdf2zh_next 异步流式翻译 ──
        logger.info(f"[{paper_id}] Starting pdf2zh_next translation …")
        output_paths = asyncio.run(
            _run_translation(paper_id, input_pdf_path, mode, page_count)
        )
        logger.info(f"[{paper_id}] Output paths: {output_paths}")

        # ── 步骤 5: 上传到 R2 ─────────────────────
        upsert_translation(paper_id, {
            "status": "uploading",
            "progress_percent": 95,
        })

        # 选择最佳输出文件:
        # 优先无水印 > 普通，严格匹配请求的模式
        target_path = None
        candidates = [
            f"no_watermark_{mode}",
            mode,
        ]

        for candidate_key in candidates:
            candidate = output_paths.get(candidate_key)
            if candidate and Path(str(candidate)).exists():
                target_path = Path(str(candidate))
                break

        if not target_path:
            raise TranslationError(
                f"翻译完成但未生成目标文件 (mode={mode})"
            )

        translated_pdf = target_path.read_bytes()
        logger.info(
            f"[{paper_id}] Read translated PDF: {len(translated_pdf)} bytes"
        )

        r2_key = f"papers/{paper_id}/translated_{mode}.pdf"
        translated_pdf_url = upload_pdf(translated_pdf, r2_key)
        logger.info(f"[{paper_id}] Uploaded → {translated_pdf_url}")

        # ── 步骤 6: 完成 ─────────────────────────
        translated_file_size = len(translated_pdf)
        upsert_translation(paper_id, {
            "status": "completed",
            "progress_percent": 100,
            "progress_current": page_count,
            "progress_total": page_count,
            "translated_count": page_count,
            "total_paragraphs": page_count,
            "translated_pdf_url": translated_pdf_url,
            "immersive_pdf_url": translated_pdf_url,
            "translated_file_size": translated_file_size,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error_message": None,
        })

        logger.info(
            f"[{paper_id}] Translation completed "
            f"({page_count} pages, mode={mode}, size={translated_file_size} bytes)"
        )
        return {
            "paper_id": paper_id,
            "status": "completed",
            "url": translated_pdf_url,
            "translated_file_size": translated_file_size,
        }

    # ── 错误处理 ────────────────────────────────────

    except FileValidationError as e:
        logger.error(f"[{paper_id}] Validation failed: {e}")
        mark_failed(paper_id, str(e))
        raise Reject(str(e), requeue=False)

    except SoftTimeLimitExceeded:
        logger.error(f"[{paper_id}] Task timed out (>30 min)")
        mark_failed(paper_id, "翻译超时 (超过 30 分钟)")
        raise

    except (TranslationError, StorageError) as e:
        logger.error(
            f"[{paper_id}] Retryable error (attempt {attempt}): {e}"
        )
        if self.request.retries >= self.max_retries:
            mark_failed(
                paper_id,
                f"翻译失败 (已重试 {self.max_retries} 次): {e}",
            )
            raise
        upsert_translation(paper_id, {
            "retry_count": self.request.retries + 1,
            "error_message": f"正在重试 … ({e})",
        })
        raise self.retry(exc=e)

    except Exception as e:
        logger.error(f"[{paper_id}] Unexpected error: {e}", exc_info=True)
        if self.request.retries >= self.max_retries:
            mark_failed(paper_id, f"未知错误: {e}")
            raise
        raise self.retry(exc=e)

    finally:
        # 清理临时文件
        if task_dir.exists():
            try:
                shutil.rmtree(task_dir, ignore_errors=True)
            except Exception:
                pass
