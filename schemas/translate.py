"""
翻译 API 的 Pydantic 模型。
"""

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class TranslateRequest(BaseModel):
    """POST /translate 的请求体"""
    paper_id: str
    file_url: str
    mode: Literal["mono", "dual"] = "dual"
    engine: str = "pdf2zh"
    queue: Literal["free_queue", "pro_queue", "ultra_queue"] = "free_queue"  # 队列选择

    @field_validator("paper_id")
    @classmethod
    def validate_paper_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("paper_id must be a valid UUID")
        return v
    
    @field_validator("queue")
    @classmethod
    def validate_queue(cls, v: str) -> str:
        valid_queues = ["free_queue", "pro_queue", "ultra_queue"]
        if v not in valid_queues:
            raise ValueError(f"queue must be one of {valid_queues}")
        return v


class TranslateResponse(BaseModel):
    """POST /translate 的响应"""
    success: bool
    celery_task_id: Optional[str] = None
    paper_id: str
    message: str


class TranslationStatusResponse(BaseModel):
    """GET /translate/status/{paper_id} 的响应"""
    paper_id: str
    status: str
    translation_mode: Optional[str] = None
    progress_percent: int = 0
    progress_current: int = 0
    progress_total: int = 0
    translated_pdf_url: Optional[str] = None
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    translate_engine: Optional[str] = None
    retry_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CancelResponse(BaseModel):
    """POST /translate/cancel/{paper_id} 的响应"""
    success: bool
    message: str
