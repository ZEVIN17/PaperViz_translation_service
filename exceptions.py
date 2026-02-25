"""
PaperViz Translation Service — 自定义异常
"""


class TranslationError(Exception):
    """翻译相关错误基类。可重试。"""
    pass


class FileValidationError(TranslationError):
    """文件校验失败（大小、MIME、页数）。不可重试。"""
    pass


class StorageError(TranslationError):
    """R2 / S3 存储操作失败。可重试。"""
    pass
