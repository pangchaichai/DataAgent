"""
tools/report_builder.py — 报告生成模块（I-2）

职责：
  1. render_report()  — Jinja2 渲染 Markdown 报告
  2. export_word()    — Markdown → python-docx Word 文件
  3. list_templates() — 返回可用模板列表
  4. ReportResult     — 标准化返回格式

设计原则：
  - 数字全部来自固化计算器，不走 LLM 生成
  - 模板与代码分离（templates/reports/*.md.j2）
  - export_word 仅做基础格式化，不处理图表（图表由 I-3 负责）
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import jinja2


# ── 模板目录 ────────────────────────────────────────────
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


# ── 数据类 ──────────────────────────────────────────────

@dataclass
class ReportResult:
    ok: bool
    markdown: str = ""
    word_path: str = ""
    template: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
#  公开接口
# ═══════════════════════════════════════════════════════════════

def list_templates() -> list[dict]:
    """返回可用报告模板列表"""
    templates_dir = _TEMPLATE_DIR / "reports"
    if not templates_dir.exists():
        return []
    result = []
    for f in templates_dir.glob("*.md.j2"):
        name = f.stem.replace(".md", "")
        labels = {
            "concentration_report": "主体集中度报告",
            "nav_report": "净值运作报告",
            "base_report": "基础报告头（不独立使用）",
        }
        result.append({
            "name": name,
            "label": labels.get(name, name),
            "path": str(f.relative_to(_TEMPLATE_DIR)),
        })
    return result


def render_report(template_name: str, data: dict) -> ReportResult:
    """
    使用 Jinja2 渲染 Markdown 报告。

    参数:
        template_name: 模板名（不含路径和 .md.j2 后缀），如 "concentration_report"
        data:          传入模板的变量字典

    返回: ReportResult（ok=True 时 markdown 字段有内容）
    """
    template_path = f"reports/{template_name}.md.j2"
    try:
        template = _JINJA_ENV.get_template(template_path)
    except jinja2.TemplateNotFound:
        return ReportResult(
            ok=False,
            error=f"模板不存在：{template_path}",
        )
    except Exception as e:
        return ReportResult(ok=False, error=f"模板加载失败：{str(e)[:200]}")

    # 注入公共变量（未提供时使用默认值）
    if "report_date" not in data:
        data["report_date"] = datetime.now().strftime("%Y-%m-%d")

    try:
        markdown = template.render(**data)
        return ReportResult(ok=True, markdown=markdown, template=template_name)
    except Exception as e:
        return ReportResult(ok=False, error=f"模板渲染失败：{str(e)[:200]}")


def export_word(markdown: str, output_path: str) -> ReportResult:
    """
    将 Markdown 字符串导出为 Word（.docx）文件。

    格式化规则：
      # → Heading 1
      ## → Heading 2
      ### → Heading 3
      | ... | → 表格（检测到竖线的行）
      - → 列表项
      空行 → 段落分隔
      加粗 **text** → 粗体 Run
      其余 → Normal 段落

    返回: ReportResult（ok=True 时 word_path 有值）
    """
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return ReportResult(
            ok=False,
            error="python-docx 未安装，请运行 pip install python-docx",
        )

    doc = Document()
    _set_document_style(doc)

    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("# "):
            _add_heading(doc, stripped[2:], level=1)
        elif stripped.startswith("## "):
            _add_heading(doc, stripped[3:], level=2)
        elif stripped.startswith("### "):
            _add_heading(doc, stripped[4:], level=3)
        elif stripped.startswith("|") and "---" not in stripped:
            # 表格：收集连续的 | 行
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if "---" not in lines[i]:
                    table_lines.append(lines[i].strip())
                i += 1
            _add_table(doc, table_lines)
            continue
        elif stripped.startswith("- ") or stripped.startswith("* "):
            _add_list_item(doc, stripped[2:])
        elif stripped.startswith("*本报告"):
            p = doc.add_paragraph(stripped)
            p.runs[0].font.size = Pt(9)
            p.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        elif stripped == "---":
            doc.add_paragraph("─" * 40)
        elif stripped:
            _add_normal_paragraph(doc, stripped)

        i += 1

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return ReportResult(ok=True, word_path=str(out_path))


# ═══════════════════════════════════════════════════════════════
#  Word 格式化辅助
# ═══════════════════════════════════════════════════════════════

def _set_document_style(doc) -> None:
    """设置文档基本样式（字体、段间距）"""
    from docx.shared import Pt
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(11)


def _add_heading(doc, text: str, level: int) -> None:
    from docx.shared import Pt, RGBColor
    heading = doc.add_heading(text, level=level)
    run = heading.runs[0] if heading.runs else heading.add_run(text)
    run.font.name = "微软雅黑"
    if level == 1:
        run.font.size = Pt(16)
    elif level == 2:
        run.font.size = Pt(14)
    else:
        run.font.size = Pt(12)


def _add_normal_paragraph(doc, text: str) -> None:
    """添加普通段落，支持 **加粗** 语法"""
    p = doc.add_paragraph()
    _add_runs_with_bold(p, text)


def _add_list_item(doc, text: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    _add_runs_with_bold(p, text)


def _add_runs_with_bold(paragraph, text: str) -> None:
    """解析 **text** 加粗语法，分段添加 Run"""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    for j, part in enumerate(parts):
        if not part:
            continue
        run = paragraph.add_run(part)
        if j % 2 == 1:
            run.bold = True


def _add_table(doc, lines: list[str]) -> None:
    """将 Markdown 表格行转换为 Word 表格"""
    if not lines:
        return

    rows_data = []
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows_data.append(cells)

    if not rows_data:
        return

    ncols = len(rows_data[0])
    table = doc.add_table(rows=len(rows_data), cols=ncols)
    table.style = "Table Grid"

    for row_idx, row_cells in enumerate(rows_data):
        for col_idx, cell_text in enumerate(row_cells[:ncols]):
            cell = table.cell(row_idx, col_idx)
            cell.text = cell_text
            if row_idx == 0:
                for run in cell.paragraphs[0].runs:
                    run.bold = True
