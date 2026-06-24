"""Tests for tools/data_masker.py — 内测脱敏防控模块"""
import pandas as pd
import pytest

from tools.data_masker import (
    _generate_masked,
    _make_seed,
    get_masking_config,
    mask_dataframe,
    parse_mask_fields,
    validate_masking_ready,
)


class TestMakeSeed:
    def test_deterministic(self):
        s1 = _make_seed("hello", 42)
        s2 = _make_seed("hello", 42)
        assert s1 == s2

    def test_different_values(self):
        s1 = _make_seed("hello", 42)
        s2 = _make_seed("world", 42)
        assert s1 != s2

    def test_different_seeds(self):
        s1 = _make_seed("hello", 42)
        s2 = _make_seed("hello", 99)
        assert s1 != s2


class TestGenerateMasked:
    def test_empty_string(self):
        assert _generate_masked("", 42) == ""

    def test_deterministic(self):
        v1 = _generate_masked("测试主体", 42)
        v2 = _generate_masked("测试主体", 42)
        assert v1 == v2

    def test_different_from_original(self):
        masked = _generate_masked("张三", 42)
        assert masked != "张三"

    def test_cjk_preserved(self):
        masked = _generate_masked("中国银行", 42)
        assert any('一' <= ch <= '鿿' for ch in masked)

    def test_alphanumeric(self):
        masked = _generate_masked("ABC123", 42)
        assert len(masked) > 0


class TestParseFields:
    def test_empty(self):
        assert parse_mask_fields("") == []
        assert parse_mask_fields(None) == []

    def test_comma_separated(self):
        result = parse_mask_fields("name,phone,address")
        assert result == ["name", "phone", "address"]

    def test_chinese_comma(self):
        result = parse_mask_fields("姓名，电话，地址")
        assert result == ["姓名", "电话", "地址"]

    def test_mixed_commas(self):
        result = parse_mask_fields("姓名,电话，地址")
        assert result == ["姓名", "电话", "地址"]

    def test_whitespace_trimmed(self):
        result = parse_mask_fields(" name , phone , addr ")
        assert result == ["name", "phone", "addr"]

    def test_empty_entries_removed(self):
        result = parse_mask_fields("name,,phone,")
        assert result == ["name", "phone"]


class TestMaskDataframe:
    def test_basic_masking(self):
        df = pd.DataFrame({
            "姓名": ["张三", "李四", "王五"],
            "金额": [100, 200, 300],
        })
        masked, mapping = mask_dataframe(df, ["姓名"])
        assert "姓名" in mapping
        assert masked["姓名"][0] != "张三"
        assert masked["姓名"][1] != "李四"
        assert list(masked["金额"]) == [100, 200, 300]

    def test_same_value_same_mask(self):
        df = pd.DataFrame({
            "主体": ["中国银行", "工商银行", "中国银行"],
        })
        masked, mapping = mask_dataframe(df, ["主体"])
        assert masked["主体"][0] == masked["主体"][2]
        assert masked["主体"][0] != masked["主体"][1]

    def test_missing_field_ignored(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        masked, mapping = mask_dataframe(df, ["nonexistent"])
        assert "nonexistent" not in mapping
        assert list(masked["a"]) == [1, 2]

    def test_empty_values_preserved(self):
        df = pd.DataFrame({"name": ["hello", "", None]})
        masked, mapping = mask_dataframe(df, ["name"])
        assert masked["name"][1] == ""

    def test_deterministic_across_calls(self):
        df = pd.DataFrame({"x": ["test"]})
        m1, _ = mask_dataframe(df.copy(), ["x"], global_seed=42)
        m2, _ = mask_dataframe(df.copy(), ["x"], global_seed=42)
        assert m1["x"][0] == m2["x"][0]

    def test_multiple_fields(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "phone": ["123", "456"],
            "score": [90, 85],
        })
        masked, mapping = mask_dataframe(df, ["name", "phone"])
        assert "name" in mapping
        assert "phone" in mapping
        assert masked["name"][0] != "Alice"
        assert masked["phone"][0] != "123"
        assert list(masked["score"]) == [90, 85]


class TestValidateMaskingReady:
    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(
            'tools.data_masker.get_masking_config',
            lambda: {'enabled': False, 'fields': ''}
        )
        ok, msg = validate_masking_ready()
        assert ok is True

    def test_enabled_with_fields(self, monkeypatch):
        monkeypatch.setattr(
            'tools.data_masker.get_masking_config',
            lambda: {'enabled': True, 'fields': '姓名,电话'}
        )
        ok, msg = validate_masking_ready()
        assert ok is True

    def test_enabled_no_fields(self, monkeypatch):
        monkeypatch.setattr(
            'tools.data_masker.get_masking_config',
            lambda: {'enabled': True, 'fields': ''}
        )
        ok, msg = validate_masking_ready()
        assert ok is False
        assert '脱敏' in msg
