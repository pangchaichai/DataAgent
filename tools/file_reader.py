"""
tools/file_reader.py — 文档解析工具（I-6）

支持格式：
  - .docx   → python-docx（文本 + 表格）
  - .pdf    → pypdf（纯文本提取，加密文件优雅降级）
  - .txt    → 直接读取

不支持格式优雅报错，不崩溃。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TableResult:
    headers: list[str]
    rows: list[list[str]]


@dataclass
class DocumentResult:
    ok: bool
    file_path: str = ""
    file_type: str = ""
    text: str = ""
    tables: list[TableResult] = field(default_factory=list)
    page_count: int = 0
    word_count: int = 0
    error: str = ""
    warnings: list[str] = field(default_factory=list)


def read_document(file_path: str, max_chars: int = 50000) -> DocumentResult:
    """
    解析文档，提取文本和表格。

    参数:
      file_path: 文件绝对路径
      max_chars: 最大提取字符数（防止超大文件撑爆内存）

    返回: DocumentResult（ok=False 时 error 字段说明原因）
    """
    path = Path(file_path)
    if not path.exists():
        return DocumentResult(ok=False, file_path=file_path, error="文件不存在")

    ext = path.suffix.lower()
    if ext == ".docx":
        return _read_docx(file_path, max_chars)
    elif ext == ".pdf":
        return _read_pdf(file_path, max_chars)
    elif ext in (".txt", ".md"):
        return _read_text(file_path, max_chars)
    else:
        return DocumentResult(
            ok=False, file_path=file_path,
            error=f"不支持的格式：{ext}（支持 .docx, .pdf, .txt）"
        )


def _read_docx(file_path: str, max_chars: int) -> DocumentResult:
    try:
        from docx import Document
    except ImportError:
        return DocumentResult(ok=False, file_path=file_path, error="python-docx 未安装")

    try:
        doc = Document(file_path)
    except Exception as e:
        return DocumentResult(ok=False, file_path=file_path, error=f"Word 文件读取失败：{e}")

    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    full_text = "\n".join(paragraphs)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + f"\n…[已截断，原文 {len(full_text)} 字符]"

    tables = []
    for tbl in doc.tables:
        if not tbl.rows:
            continue
        headers = [cell.text.strip() for cell in tbl.rows[0].cells]
        rows = [
            [cell.text.strip() for cell in row.cells]
            for row in tbl.rows[1:]
        ]
        tables.append(TableResult(headers=headers, rows=rows))

    return DocumentResult(
        ok=True, file_path=file_path, file_type="docx",
        text=full_text, tables=tables,
        page_count=0, word_count=len(full_text.split()),
    )


def _read_pdf(file_path: str, max_chars: int) -> DocumentResult:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        return DocumentResult(ok=False, file_path=file_path, error="pypdf 未安装")
    except Exception:
        return DocumentResult(ok=False, file_path=file_path, error="PDF 依赖加载失败（环境问题）")

    try:
        reader = PdfReader(file_path)
    except Exception as e:
        return DocumentResult(ok=False, file_path=file_path, error=f"PDF 读取失败：{e}")

    page_count = len(reader.pages)
    texts = []
    total_chars = 0
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
            texts.append(t)
            total_chars += len(t)
            if total_chars > max_chars:
                warnings.append(f"内容已截断（前 {i+1} 页，{total_chars} 字符）")
                break
        except Exception:
            warnings.append(f"第 {i+1} 页提取失败，已跳过")

    full_text = "\n\n".join(texts)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars]

    return DocumentResult(
        ok=True, file_path=file_path, file_type="pdf",
        text=full_text, tables=[],
        page_count=page_count,
        word_count=len(full_text.split()),
        warnings=warnings,
    )


def _read_text(file_path: str, max_chars: int) -> DocumentResult:
    warnings: list[str] = []
    try:
        import chardet
        with open(file_path, 'rb') as f:
            raw = f.read(200000)
        enc = chardet.detect(raw).get('encoding') or 'utf-8'
        text = raw.decode(enc, errors='replace')
    except Exception as e:
        return DocumentResult(ok=False, file_path=file_path, error=f"文本读取失败：{e}")

    if len(text) > max_chars:
        text = text[:max_chars]
        warnings.append(f"内容已截断至 {max_chars} 字符")

    return DocumentResult(
        ok=True, file_path=file_path, file_type="txt",
        text=text, tables=[],
        page_count=1, word_count=len(text.split()),
        warnings=warnings,
    )
