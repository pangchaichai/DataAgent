"""
tools/encoding.py — 编码检测 + 列名清洗

从 data_loader.py 拆分而来。职责：
  1. 多编码竞争评分，自动选最优编码
  2. 列名清洗（去首尾空格、去不可见字符）
  3. 千分位数值分隔符清洗
"""

import re

import chardet
import pandas as pd


def _is_cjk_char(cp: int) -> bool:
    """判断码点是否为 CJK 统一表意文字（含扩展区）"""
    return (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or \
           (0x20000 <= cp <= 0x2FFFF) or (0xF900 <= cp <= 0xFAFF)


def _is_suspicious_char(cp: int) -> bool:
    """判断码点是否为可疑的乱码特征字符（box-drawing、Cyrillic、Latin-Ext等）
    这些字符出现在假定为中文的列名中通常意味着编码错误。"""
    return (0x2500 <= cp <= 0x257F) or (0x0400 <= cp <= 0x04FF) or \
           (0x0100 <= cp <= 0x024F)


def _score_encoding(file_path: str, encoding: str) -> tuple[int, str]:
    """
    尝试用指定编码读取 CSV，对解码质量综合评分。
    返回 (score, reason)，分数越高越好。负分表示不可用。
    """
    import io
    try:
        with open(file_path, 'rb') as f:
            raw = f.read(200000)
        text = raw.decode(encoding)
        lines = text.split('\n')
        if len(lines) < 2:
            return (-1, "行数不足")

        header = lines[0]
        if not header.strip():
            return (-1, "空表头")

        score = 0
        cjk = suspicious = ascii_chars = 0

        for ch in header:
            cp = ord(ch)
            if _is_cjk_char(cp):
                cjk += 1
            elif _is_suspicious_char(cp):
                suspicious += 1
            elif cp < 128:
                ascii_chars += 1

        score += cjk * 2
        score += ascii_chars * 0.1
        score -= suspicious * 3

        if cjk == 0 and suspicious == 0:
            score = 10

        try:
            pd.read_csv(io.StringIO(text), dtype=str,
                        nrows=5, keep_default_na=False, na_values=[''])
            score += 5
        except Exception:
            score -= 10

        reason = (f"CJK={cjk} suspect={suspicious} ascii={ascii_chars} "
                  f"→ score={score}")
        return (score, reason)

    except (UnicodeDecodeError, LookupError):
        return (-100, f"无法用 {encoding} 解码")


def detect_encoding(file_path: str, sample_bytes: int = 50000) -> str:
    """★ 自适应编码检测：多编码竞争评分，自动选最优 ★"""
    candidates = ['utf-8', 'gb18030', 'gbk', 'gb2312', 'latin-1']

    try:
        with open(file_path, 'rb') as f:
            raw = f.read(sample_bytes)

        has_bom = raw[:3] == b'\xef\xbb\xbf'

        chardet_result = chardet.detect(raw)
        chardet_enc = chardet_result.get('encoding', 'utf-8')
        if chardet_enc:
            chardet_enc = _normalize_encoding(chardet_enc)
        if chardet_enc and chardet_enc not in candidates:
            candidates.insert(0, chardet_enc)
        elif chardet_enc in candidates:
            candidates.remove(chardet_enc)
            candidates.insert(0, chardet_enc)

        if has_bom and 'utf-8' in candidates:
            candidates.remove('utf-8')
            candidates.insert(0, 'utf-8')
    except Exception:
        pass

    best_score = -999
    best_enc = 'utf-8'
    results = []

    for enc in candidates:
        score, reason = _score_encoding(file_path, enc)
        results.append((enc, score, reason))
        if score > best_score:
            best_score = score
            best_enc = enc

    results.sort(key=lambda x: x[1], reverse=True)
    for enc, _score, reason in results[:4]:
        marker = ' ★' if enc == best_enc else ''
        print(f"[encoding]   {enc}: {reason}{marker}")

    if best_score < 0:
        print("[encoding] ⚠️ 所有编码评分均为负，退回 utf-8")

    return best_enc


def _normalize_encoding(enc: str) -> str:
    """将编码名称归一化为 DuckDB/Pandas 通用名。"""
    upper = enc.upper().replace('-', '').replace('_', '')
    if upper in ('UTF8SIG', 'UTF8BOM'):
        return 'utf-8'
    return enc


def clean_column_name(name: str) -> str:
    """
    清洗列名：去首尾空格、去不可见字符、去 BOM。
    """
    name = name.strip()
    name = name.lstrip('﻿')
    name = re.sub(r'[​‌‍⁠﻿]', '', name)
    return name


def clean_thousands_separator(value) -> str:
    """移除千分位逗号：'1,234,567.89' → '1234567.89'"""
    s = str(value).strip()
    if not s or s.lower() == 'nan':
        return s
    if re.match(r'^-?[\d,]+\.?\d*$', s):
        s = s.replace(',', '')
    return s
