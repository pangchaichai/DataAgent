"""
tests/test_workdir_loader.py — 工作目录加载器单元测试
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.workdir_loader import list_workdir_files, scan_for_pattern


def _make_workdir(files: list[str]) -> Path:
    """创建临时工作目录并写入指定文件。"""
    tmp = tempfile.mkdtemp()
    for fname in files:
        (Path(tmp) / fname).write_text("col1,col2\n1,2\n", encoding='utf-8')
    return Path(tmp)


def test_list_workdir_files_no_config():
    """未配置工作目录时返回空列表。"""
    with patch('tools.workdir_loader.get_work_dir', return_value=None):
        assert list_workdir_files() == []


def test_list_workdir_files_empty_dir():
    """工作目录为空时返回空列表。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch('tools.workdir_loader.get_work_dir', return_value=Path(tmp)):
            result = list_workdir_files()
            assert result == []


def test_list_workdir_files_csv_only():
    """只返回 CSV/Excel 文件，忽略其他文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'data.csv').write_text('a,b\n1,2', encoding='utf-8')
        (Path(tmp) / 'notes.txt').write_text('hello', encoding='utf-8')
        (Path(tmp) / 'report.xlsx').write_text('', encoding='utf-8')
        with patch('tools.workdir_loader.get_work_dir', return_value=Path(tmp)):
            result = list_workdir_files()
            names = [f['filename'] for f in result]
            assert 'data.csv' in names
            assert 'report.xlsx' in names
            assert 'notes.txt' not in names


def test_list_workdir_files_metadata():
    """返回的文件信息包含必要字段。"""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / '周报-数据源.csv').write_text('a,b\n1,2', encoding='utf-8')
        with patch('tools.workdir_loader.get_work_dir', return_value=Path(tmp)):
            result = list_workdir_files()
            assert len(result) == 1
            f = result[0]
            assert 'filename' in f
            assert 'size_kb' in f
            assert 'mtime' in f
            assert 'path' in f


def test_scan_for_pattern_no_workdir():
    """工作目录未配置时返回空列表。"""
    with patch('tools.workdir_loader.get_work_dir', return_value=None):
        assert scan_for_pattern('周报*数据源*') == []


def test_scan_for_pattern_fnmatch_exact():
    """精确 fnmatch 匹配。"""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / '周报-本周数据源.csv').write_text('a,b\n', encoding='utf-8')
        (Path(tmp) / '其他文件.csv').write_text('a,b\n', encoding='utf-8')
        with patch('tools.workdir_loader.get_work_dir', return_value=Path(tmp)):
            result = scan_for_pattern('周报*数据源*')
            assert len(result) == 1
            assert result[0]['filename'] == '周报-本周数据源.csv'


def test_scan_for_pattern_substring_fallback():
    """fnmatch 不匹配时回退到子串匹配。"""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / '信用数据表_2026.csv').write_text('a,b\n', encoding='utf-8')
        with patch('tools.workdir_loader.get_work_dir', return_value=Path(tmp)):
            # 使用不含通配符的 pattern，触发子串匹配
            result = scan_for_pattern('信用数据')
            assert len(result) == 1


def test_scan_for_pattern_no_match():
    """无匹配时返回空列表。"""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / '其他文件.csv').write_text('a,b\n', encoding='utf-8')
        with patch('tools.workdir_loader.get_work_dir', return_value=Path(tmp)):
            result = scan_for_pattern('周报*数据源*')
            assert result == []


def test_scan_for_pattern_empty_pattern():
    """空 pattern 返回空列表。"""
    with patch('tools.workdir_loader.get_work_dir', return_value=None):
        assert scan_for_pattern('') == []


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
