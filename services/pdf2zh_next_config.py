"""
PDFMathTranslate-next (pdf2zh_next) 2.0 Settings Factory

构建用于调用 do_translate_async_stream 的 SettingsModel。
支持 QwenMT（DashScope 专用 MT）和 OpenAI 兼容引擎。

⚠️ 本模块 import pdf2zh_next，受 AGPL-3.0 约束。
"""

import logging
import os
from pathlib import Path

from pdf2zh_next import (
    BasicSettings,
    OpenAISettings,
    PDFSettings,
    QwenMtSettings,
    SettingsModel,
    TranslationSettings,
)

from config import DASHSCOPE_API_KEY, LLM_TRANSLATE_MODEL

logger = logging.getLogger("translation_service.pdf2zh_config")

# 翻译 I/O 临时工作目录
WORK_DIR = Path(os.getenv("PDF2ZH_WORK_DIR", "/tmp/pdf2zh_next"))


def get_translate_engine_settings():
    """
    根据环境变量构建翻译引擎设置。

    通过 PDF2ZH_ENGINE 环境变量支持两种模式：
      - "qwenmt"（默认）: 使用 QwenMtSettings + DashScope MT API
      - "openai": 使用 OpenAISettings + 可配置的 base_url/model
    """
    engine_type = os.getenv("PDF2ZH_ENGINE", "qwenmt").lower()

    if engine_type == "openai":
        return OpenAISettings(
            openai_api_key=os.getenv("OPENAI_API_KEY", DASHSCOPE_API_KEY),
            openai_base_url=os.getenv(
                "OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            openai_model=os.getenv("OPENAI_MODEL") or os.getenv("LLM_TRANSLATE_MODEL") or "qwen-plus",
        )

    # 默认: QwenMT（DashScope 专用机器翻译）
    return QwenMtSettings(
        qwenmt_api_key=DASHSCOPE_API_KEY,
        qwenmt_model=os.getenv("QWENMT_MODEL", "qwen-mt-plus"),
    )


def build_settings(
    mode: str = "dual",
    lang_in: str = "en",
    lang_out: str = "zh-CN",
) -> SettingsModel:
    """
    构建经过校验的 pdf2zh_next 2.0 SettingsModel。

    Parameters
    ----------
    mode : str
        "mono" = 仅中文翻译 PDF
        "dual" = 中英双语对照 PDF
        "both" = 同时生成 mono 和 dual
    lang_in : str
        源语言代码（默认: "en"）
    lang_out : str
        目标语言代码（默认: "zh-CN"，QwenMT 要求）

    Returns
    -------
    SettingsModel
        经过校验、可直接用于 do_translate_async_stream 的设置。
    """
    # 确定 mono/dual 标志
    # PDFSettings: no_mono=True 表示跳过 mono, no_dual=True 表示跳过 dual
    no_mono = mode == "dual"
    no_dual = mode == "mono"

    settings = SettingsModel(
        report_interval=0.5,
        basic=BasicSettings(
            debug=os.getenv("PDF2ZH_DEBUG", "").lower() in ("1", "true"),
        ),
        translation=TranslationSettings(
            lang_in=lang_in,
            lang_out=lang_out,
            output=str(WORK_DIR / "output"),
        ),
        pdf=PDFSettings(
            no_mono=no_mono,
            no_dual=no_dual,
            watermark_output_mode="no_watermark",
            translate_table_text=True,
        ),
        translate_engine_settings=get_translate_engine_settings(),
    )

    settings.validate_settings()
    logger.info(
        f"pdf2zh_next settings built: engine={type(settings.translate_engine_settings).__name__}, "
        f"mode={mode}, lang={lang_in}->{lang_out}"
    )
    return settings
