# PaperViz Translation Service

## 一、 服务名称与简介
PaperViz Translation Service 是一个独立且专注于高质量学术文档翻译的微服务系统。基于高性能的异步架构（FastAPI + Celery），本服务可无缝处理大规模多页 PDF 文档的版式解析、翻译合并与双语输出渲染。

## 二、 上游开源项目信息
本服务的核心翻译版面保留及合并能力深度依赖以下出色的开源项目：
- **项目名称**：pdf2zh-next (上游演进自 PDFMathTranslate-next)
- **项目仓库**：[https://github.com/PDFMathTranslate/PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next)
- **开源协议**：**GNU Affero General Public License v3.0 (AGPL-3.0)**
- **版权声明**：Copyright © 2024 The PDFMathTranslate Authors (Bytedance).

## 三、 本服务用途
本服务是对 pdf2zh-next 库进行了 API Server 级别的二次工程封装，旨在稳定支持 SaaS 级并发调度。其具体用途与功能包括：
- **PDF 学术翻译**：将英文等语言的高难度版式 PDF（特别是顶级学术期刊）翻译为中文。
- **公式保留**：在翻译过程中智能检测并保留原生公式格式与坐标。
- **双语对照**：自动化将翻译结果合并排版，输出中英双语对照、无水印的高质量 PDF 文件。

## 四、 AGPL-3.0 协议说明与合规声明
> **重要合规声明**：本服务（PaperViz Translation Service）由于直接引入并封装了基于 AGPL-3.0 的 pdf2zh-next，根据协议规定，**本微服务的全部源代码连同其外部 API 封装配置均必须以 GNU Affero General Public License v3.0 (AGPL-3.0) 协议开源。**

依据 AGPL-3.0 的核心条款约束，您在二次分发或使用本微服务时须遵守：
1. **修改与网络分发开源义务**：即使您未分发客户端二进制程序，仅将本微服务**运行于云端作为向用户提供网络服务的后端（Network Service）**，如果您对本服务的源码或其上游（pdf2zh-next）做了定制修改并投入生产环境，您**必须**向有权访问该网络服务的用户提供修改后的完整源代码。
2. **闭源隔离**：如果您正在开发商业闭源软件，强烈建议您保留当前的微服务拆分架构。即，请保持本 Translation Service 的独立性（网络与进程解耦），通过 HTTP/RESTful 通讯交互，不得将其中的代码模块（如 `.py` 文件模块）直接静态加载到您的闭源代码库中。
3. **信息公开**：必须在合理的位置明示使用者，其正在使用的功能由基于 AGPL-3.0 条款的代码提供支撑。

附录条款全文：[GNU AGPL-3.0 License 原文](https://www.gnu.org/licenses/agpl-3.0.html)

## 五、 部署与使用简要说明
**环境依赖**：
- Python 3.11+
- 系统级依赖：`curl`, `libgl1`, `libglib2.0-0`（用于 PDF 布局模型）
- 翻译引擎 API Key（支持 DashScope 或 OpenAI 兼容格式）

**快速启动**：
```bash
# 1. 安装系统与 Python 依赖
pip install -r requirements.txt

# 2. 启动 FastAPI Web 接口层
uvicorn main:app --host 0.0.0.0 --port 8000

# 3. 启动用于运行 pdf2zh_next 的 Celery Worker 队列
celery -A celery_app worker -l info --concurrency=4
```

## 六、 合规提示
- **源码获取**：本项目的 Git 代码仓库（即本级目录下的全部内容）是对所有人开放获取的开源代码，随时可下载拉取。
- **修改反馈**：欢迎通过开源社区的方式将任何缺陷补丁或重构优化推送到本仓库 (Pull Request)。涉及上游翻译底层核心算法的问题，可向原仓库报告。
- **架构澄清**：本隔离模块在商业架构中仅承担原子 API 能力节点，其他计费、权限鉴定等非 AGPL 模块独立于此服务外运行。

## 七、 版权声明与致谢
本服务站在这项杰出工作的肩膀上。特别感谢 [PDFMathTranslate](https://github.com/Bytedance/pdfmathtranslate) 及社区维护者提供的优异基座能力。
This service wraps `pdf2zh-next` under the AGPL-3.0 license. All credits for the core PDF processing and layout translation algorithms belong to their respective authors and bypassers.
