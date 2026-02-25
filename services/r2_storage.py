"""
Cloudflare R2 (S3 兼容) 存储助手。

提供 Celery 翻译任务使用的下载/上传功能。
"""

import ipaddress
import logging
from urllib.parse import urlparse

import boto3
import httpx

from config import (
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
    R2_PUBLIC_URL,
    R2_ALLOWED_DOMAINS,
)
from exceptions import StorageError

logger = logging.getLogger("translation_service.r2_storage")

# ── SSRF 防护 ─────────────────────────────────────────
# 禁止访问的内网 IP 范围
INTERNAL_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # AWS 元数据端点
    ipaddress.ip_network("224.0.0.0/4"),    # 多播
    ipaddress.ip_network("240.0.0.0/4"),    # 保留
]


def _is_internal_ip(ip_str: str) -> bool:
    """检查 IP 是否为内网/私有 IP。"""
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in INTERNAL_IP_RANGES:
            if ip in network:
                return True
    except ValueError:
        # 不是有效的 IP 地址
        pass
    return False


def _validate_url(url: str) -> bool:
    """
    验证 URL 是否安全，防止 SSRF 攻击。
    
    检查规则：
    1. 域名必须在允许列表中（白名单）
    2. 禁止解析到内网 IP
    """
    if not url.startswith("http"):
        return True  # 非 HTTP URL 后续会走 R2 逻辑
    
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        
        if not hostname:
            logger.warning(f"URL 解析失败，无效的主机名: {url}")
            return False
        
        # 检查是否为 IP 地址
        if _is_internal_ip(hostname):
            logger.warning(f"SSRF 防护: 禁止访问内网 IP {hostname}")
            return False
        
        # 检查域名是否在白名单中
        if R2_ALLOWED_DOMAINS:
            allowed_list = [d.strip().lower() for d in R2_ALLOWED_DOMAINS.split(",")]
            if hostname.lower() not in allowed_list:
                logger.warning(f"SSRF 防护: 域名 {hostname} 不在允许列表中")
                return False
        
    except Exception as e:
        logger.warning(f"URL 验证异常: {e}")
        return False
    
    return True


def _get_s3_client():
    """创建指向 Cloudflare R2 的 boto3 S3 客户端。"""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def download_pdf(file_url: str) -> bytes:
    """
    从 R2（或任意公网 URL）下载 PDF。

    解析顺序:
    1. 直接 HTTP URL（如果 file_url 以 http 开头）
    2. R2 公网 URL + 相对 key
    3. R2 S3 API + 相对 key
    
    安全检查:
    - HTTP URL 必须通过 SSRF 防护验证
    - 只允许访问白名单域名
    - 禁止访问内网 IP
    """
    # ── 1. 直接 URL ─────────────────────────────────
    if file_url.startswith("http"):
        # SSRF 防护验证
        if not _validate_url(file_url):
            logger.warning(f"SSRF 防护: 拒绝下载不安全的 URL: {file_url}")
            raise StorageError(f"URL 安全验证失败: {file_url}")
        
        try:
            resp = httpx.get(file_url, timeout=60.0, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 0:
                logger.info(f"Downloaded PDF via URL: {len(resp.content)} bytes")
                return resp.content
        except Exception as e:
            logger.warning(f"Direct URL download failed: {e}")

    # ── 2. R2 公网 URL ─────────────────────────────
    r2_key = file_url.lstrip("/")
    if R2_PUBLIC_URL and r2_key:
        public_url = f"{R2_PUBLIC_URL.rstrip('/')}/{r2_key}"
        try:
            resp = httpx.get(public_url, timeout=60.0, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 0:
                logger.info(
                    f"Downloaded PDF via R2 public URL: {len(resp.content)} bytes"
                )
                return resp.content
        except Exception as e:
            logger.warning(f"R2 public URL download failed: {e}")

    # ── 3. R2 S3 API ─────────────────────────────
    if R2_ACCESS_KEY_ID and r2_key:
        try:
            s3 = _get_s3_client()
            obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=r2_key)
            data = obj["Body"].read()
            logger.info(f"Downloaded PDF via R2 S3 API: {len(data)} bytes")
            return data
        except Exception as e:
            logger.warning(f"R2 S3 API download failed: {e}")

    raise StorageError(f"Cannot download PDF from: {file_url}")


def upload_pdf(pdf_bytes: bytes, key: str) -> str:
    """
    上传 PDF 到 R2。

    返回已上传文件的公网 URL。
    """
    try:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        url = f"{R2_PUBLIC_URL.rstrip('/')}/{key}" if R2_PUBLIC_URL else key
        logger.info(f"Uploaded PDF to R2: {key} ({len(pdf_bytes)} bytes)")
        return url
    except Exception as e:
        raise StorageError(f"Failed to upload to R2: {e}")
