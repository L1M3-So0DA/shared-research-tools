# shared-research-tools

实验室学术研究辅助工具集，包含通用自动化脚本、SKILL 程序库及标准化技术文档。

## 仓库定位

本仓库用于沉淀实验室在学术研究流程中的通用资产，尽量与具体课题解耦，重点覆盖文档规范、格式转换、专利写作和 SKILL 开发等可复用工作流。

## 目录说明

| 路径 | 内容 | 说明 |
| --- | --- | --- |
| docs/ | 团队文档与经验沉淀 | 存放研究流程、工具使用和协作经验类文档。 |
| skills/ | SKILL 库 | 存放可复用的 SKILL 及其配套资源。 |
| skills/third_party/ | 第三方 SKILL | 存放外部引入的 SKILL 及其原始资源。 |

## SKILL 作用一览

| SKILL | 作用 | 适用场景 |
| --- | --- | --- |
| pandoc-md-publish | 将 Markdown 发布为 Word 或 PDF，并在转换前后检查引用、图表、公式和 Pandoc 警告。 | 论文、报告、讲义、技术说明的导出和排错。 |
| patent-writing | 将技术方案整理为中文发明专利草案或软件著作权材料，支持按模板补写、改写和扩写。 | 专利交底书、发明点整理、权利要求前置材料、已有专利改写。 |
| third_party/doc-to-markdown | 将 DOCX/PDF/PPTX/XLSX 等文档转换为高质量 Markdown，并进行后处理和结果验证。 | 批量文档转码、保留表格/图片、整理资料到 Markdown。 |
| third_party/skill-creator | 创建、改进、评测和调优 SKILL，支持测试提示词、对比基线和查看评测结果。 | 新建 SKILL、优化 SKILL 触发词、跑评测和做迭代。 |

## 许可证声明

本仓库采用双重许可协议 (Dual-licensed)及第三方代码隔离策略：

* **代码资产**：所有软件源代码（包括但不限于 Python、Bash、SKILL、VBA 脚本等）均基于 [MIT License](LICENSE) 授权。
* **文档资产**：所有学术文档、部署规范及理论说明（如 `docs/` 目录内的 `.md`、`.pdf` 文件等）均基于 [Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/) 授权。未经明确授权，严禁将文档内容用于商业用途。
* **第三方资产**：`skills/third_party/` 目录下的代码文件保持其原始的开源协议（如 Apache License 2.0），具体协议条款与版权归属详见各文件头部的法律声明。