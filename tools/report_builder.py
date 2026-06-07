"""
tools/report_builder.py — 报告渲染与 Word 导出

功能：
  1. render_report()  — Jinja2 模板 + 数据 → Markdown 字符串
  2. export_word()    — Markdown 字符串 → .docx 文件（python-docx）
  3. save_report()    — 保存到 data/outputs/
"""

import re
import time
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE_DIR / 'data' / 'outputs'


# ═══════════════════════════════════════════════════════════════
#  Markdown → Word 转换
# ═══════════════════════════════════════════════════════════════

def export_word(markdown_text: str, output_path: str) -> dict:
    """
    将 Markdown 文本导出为 Word .docx 文件。

    支持：标题（#/##/###）、粗体（**text**）、列表（- / 数字.）、
    表格（|col|col|）、普通段落。

    返回 {"ok": True, "path": str} 或 {"ok": False, "error": str}
    """
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return {"ok": False, "error": "缺少 python-docx，请运行 pip install python-docx"}

    doc = Document()

    # 设置正文默认字体
    style = doc.styles['Normal']
    style.font.name = '宋体'
    style.font.size = Pt(11)

    lines = markdown_text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]

        # 标题
        if line.startswith('### '):
            p = doc.add_heading(line[4:].strip(), level=3)
        elif line.startswith('## '):
            p = doc.add_heading(line[3:].strip(), level=2)
        elif line.startswith('# '):
            p = doc.add_heading(line[2:].strip(), level=1)

        # 水平线 (---/===)
        elif re.match(r'^[-=]{3,}$', line.strip()):
            doc.add_paragraph('─' * 30)

        # 表格（连续的 | 行）
        elif line.strip().startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i])
                i += 1
            _add_table(doc, table_lines)
            continue

        # 无序列表
        elif re.match(r'^\s*[-*]\s+', line):
            text = re.sub(r'^\s*[-*]\s+', '', line)
            p = doc.add_paragraph(style='List Bullet')
            _add_runs(p, text)

        # 有序列表
        elif re.match(r'^\s*\d+\.\s+', line):
            text = re.sub(r'^\s*\d+\.\s+', '', line)
            p = doc.add_paragraph(style='List Number')
            _add_runs(p, text)

        # 引用
        elif line.startswith('> '):
            p = doc.add_paragraph(line[2:].strip())
            p.style = doc.styles['Normal']
            p.paragraph_format.left_indent = Pt(20)
            p.runs[0].font.color.rgb = RGBColor(0x5C, 0x63, 0x70) if p.runs else None

        # 空行
        elif not line.strip():
            doc.add_paragraph('')

        # 普通段落
        else:
            p = doc.add_paragraph()
            _add_runs(p, line)

        i += 1

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return {"ok": True, "path": str(out)}


def _add_runs(paragraph, text: str):
    """解析内联 Markdown（**粗体**、*斜体*）并添加 runs"""
    # 简单解析：交替处理普通文本和格式标记
    parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith('*') and part.endswith('*'):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        elif part.startswith('`') and part.endswith('`'):
            run = paragraph.add_run(part[1:-1])
            run.font.name = 'Courier New'
        elif part:
            paragraph.add_run(part)


def _add_table(doc, lines: list):
    """将 Markdown 表格行转换为 Word 表格"""
    rows_data = []
    for line in lines:
        # 跳过分隔符行（---|---）
        if re.match(r'^\|[\s\-:|]+\|', line):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        rows_data.append(cells)

    if not rows_data:
        return

    max_cols = max(len(r) for r in rows_data)
    table = doc.add_table(rows=len(rows_data), cols=max_cols)
    table.style = 'Table Grid'

    for r_idx, row_data in enumerate(rows_data):
        row = table.rows[r_idx]
        for c_idx, cell_text in enumerate(row_data):
            if c_idx < max_cols:
                cell = row.cells[c_idx]
                cell.text = cell_text
                if r_idx == 0:
                    for run in cell.paragraphs[0].runs:
                        run.bold = True


# ═══════════════════════════════════════════════════════════════
#  报告渲染
# ═══════════════════════════════════════════════════════════════

def render_report(template_path: str, data: dict) -> str:
    """使用 Jinja2 模板渲染报告，返回 Markdown 字符串"""
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
        tmpl_path = Path(template_path)
        env = Environment(
            loader=FileSystemLoader(str(tmpl_path.parent)),
            undefined=StrictUndefined,
        )
        template = env.get_template(tmpl_path.name)
        return template.render(**data)
    except Exception as e:
        raise RuntimeError(f"模板渲染失败：{e}") from e


def save_report(content: str, filename: str) -> str:
    """保存报告 Markdown 到 data/outputs/ 并返回文件路径"""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUTS_DIR / filename
    out_path.write_text(content, encoding='utf-8')
    return str(out_path)


def export_report_word(content: str, report_name: str) -> dict:
    """
    将报告 Markdown 字符串导出为 Word 文件，保存到 data/outputs/。
    返回 {"ok": True, "filename": str, "path": str}
    """
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{report_name}_{ts}.docx"
    out_path = str(OUTPUTS_DIR / filename)
    return export_word(content, out_path) | {"filename": filename}
