"""
Celery 应用配置。

该模块同时被 FastAPI Web 进程（提交任务）和 Celery Worker 进程（执行任务）引入。

启动 Worker:
    celery -A celery_app worker --loglevel=info --concurrency=2 -Q free_queue  # 标准版
    celery -A celery_app worker --loglevel=info --concurrency=10 -Q pro_queue  # 专业版
    celery -A celery_app worker --loglevel=info --concurrency=20 -Q ultra_queue  # 科研版/内部版
"""

from celery import Celery
from config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery(
    "translation_service",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["tasks.translate"],
)

# 定义三个队列及优先级
# free_queue: 标准版 - 最低优先级
# pro_queue: 专业版 - 中等优先级
# ultra_queue: 科研版/内部版 - 最高优先级
celery_app.conf.update(
    # 队列配置
    task_routes={
        'tasks.translate_paper': {
            'queue': 'free_queue',  # 默认队列
        },
    },
    task_default_queue='free_queue',
    task_default_exchange='translation',
    task_default_routing_key='translation',

    # Pool: solo 避免 daemon workers；pdf2zh_next 会启动子进程进行翻译
    worker_pool="solo",

    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="UTC",
    enable_utc=True,

    # 可靠性
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,

    # 超时（秒）- 针对不同队列可以设置不同超时
    task_soft_time_limit=1800,   # 30 分钟软超时
    task_time_limit=2100,        # 35 分钟硬超时

    # Broker
    broker_connection_retry_on_startup=True,

    # 结果过期时间
    result_expires=86400,        # 24 小时
)
