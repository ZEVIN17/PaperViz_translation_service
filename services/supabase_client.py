"""
Supabase REST API 客户端 — 管理翻译记录。

使用 Supabase 提供的 PostgREST API — 所有调用为同步
（适用于 Celery Worker 上下文）。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger("translation_service.supabase")

# 内部状态名称到数据库 CHECK 约束允许值的映射
# 当前数据库允许: pending, extracting, translating, completed, failed
_STATUS_MAP = {
    "queued": "pending",
    "downloading": "extracting",
    "translating": "translating",
    "uploading": "translating",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "failed",
}


def _map_status(data: dict) -> dict:
    """将 'status' 映射为数据库安全值。"""
    if "status" in data:
        raw = data["status"]
        mapped = _STATUS_MAP.get(raw, raw)
        if mapped != raw:
            logger.debug(f"Status mapped: {raw} -> {mapped}")
        data["status"] = mapped
    return data


def _headers() -> dict:
    """标准 Supabase 请求头。"""
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def upsert_translation(paper_id: str, data: dict) -> None:
    """
    创建或更新 ``paper_translations`` 表中的记录。

    每次调用自动设置 ``paper_id`` 和 ``updated_at``。
    """
    data["paper_id"] = paper_id
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data = _map_status(data)

    with httpx.Client(timeout=15.0) as client:
        resp = client.get(
            f"{SUPABASE_URL}/rest/v1/paper_translations"
            f"?paper_id=eq.{paper_id}&select=id",
            headers=_headers(),
        )
        exists = resp.status_code == 200 and resp.json()

        if exists:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/paper_translations"
                f"?paper_id=eq.{paper_id}",
                headers=_headers(),
                json=data,
            )
        else:
            data.setdefault("status", "pending")
            data.setdefault("progress_percent", 0)
            data.setdefault("progress_current", 0)
            data.setdefault("progress_total", 0)
            data.setdefault("retry_count", 0)
            data.setdefault("total_paragraphs", 0)
            data.setdefault("translated_count", 0)
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/paper_translations",
                headers=_headers(),
                json=data,
            )

        if resp.status_code not in (200, 201, 204):
            logger.error(
                f"[{paper_id}] Supabase upsert failed: "
                f"{resp.status_code} {resp.text[:300]}"
            )


def get_translation(paper_id: str) -> Optional[dict]:
    """获取指定论文的翻译记录。"""
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(
            f"{SUPABASE_URL}/rest/v1/paper_translations"
            f"?paper_id=eq.{paper_id}&select=*",
            headers=_headers(),
        )
        if resp.status_code != 200:
            return None
        rows = resp.json()
        return rows[0] if rows else None


def mark_failed(paper_id: str, error_message: str) -> None:
    """便捷方法：将翻译标记为 ``failed``。"""
    upsert_translation(paper_id, {
        "status": "failed",
        "error_message": error_message[:1000],
    })


def mark_cancelled(paper_id: str) -> None:
    """便捷方法：将翻译标记为 ``cancelled``。"""
    upsert_translation(paper_id, {
        "status": "cancelled",
        "error_message": None,
    })
