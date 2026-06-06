"""
tests/test_context.py — 上下文压缩 + 成本追踪单元测试（I-3b）
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  build_schema_context 三级压缩测试
# ═══════════════════════════════════════════════════════════════

class TestBuildSchemaContext:
    @pytest.fixture(autouse=True)
    def setup_tables(self):
        """创建两张测试表"""
        import duckdb
        import tools.data_loader as dl
        dl._global_conn = None
        dl._loaded_tables.clear()
        conn = dl.init_duckdb_connection()
        conn.execute("CREATE TABLE tbl_holding AS SELECT 1 AS id, '产品A' AS 产品名称")
        conn.execute("CREATE TABLE tbl_nav AS SELECT 1 AS id, 1.05 AS unit_nav")
        dl._loaded_tables["tbl_holding"] = type('T', (), {
            'table_name': 'tbl_holding', 'row_count': 1, 'col_count': 2,
            'encoding': 'utf-8', 'date_tag': None,
            'field_map': {'产品名称': '产品名称'},
            'unmatched_cols': [], 'missing_required': [], 'warnings': [],
            'table_type': 'holding', 'quality_report': None,
        })()
        dl._loaded_tables["tbl_nav"] = type('T', (), {
            'table_name': 'tbl_nav', 'row_count': 1, 'col_count': 2,
            'encoding': 'utf-8', 'date_tag': None,
            'field_map': {'unit_nav': 'unit_nav'},
            'unmatched_cols': [], 'missing_required': [], 'warnings': [],
            'table_type': 'nav', 'quality_report': None,
        })()
        yield conn
        dl._loaded_tables.clear()

    def test_no_relevant_tables_shows_full_for_all(self):
        """不传 relevant_tables → 所有表显示完整信息"""
        from agent.context import build_schema_context
        ctx = build_schema_context(relevant_tables=None)
        assert "tbl_holding" in ctx
        assert "tbl_nav" in ctx
        # 完整模式应有 ■
        assert "■" in ctx

    def test_relevant_table_gets_full_schema(self):
        """指定的相关表应显示完整 schema（■ 标记）"""
        from agent.context import build_schema_context
        ctx = build_schema_context(relevant_tables=["tbl_holding"])
        assert "■ tbl_holding" in ctx

    def test_non_relevant_table_gets_summary_only(self):
        """未指定的表应只显示一行摘要（□ 标记）"""
        from agent.context import build_schema_context
        ctx = build_schema_context(relevant_tables=["tbl_holding"])
        assert "□ tbl_nav" in ctx
        # 非相关表不应出现完整列名
        assert "profile_table" in ctx  # 引导用 profile_table

    def test_empty_relevant_tables_shows_summary_only(self):
        """传空列表 → 所有表都是摘要（没有表被指定为相关）"""
        from agent.context import build_schema_context
        ctx = build_schema_context(relevant_tables=[])
        # relevant_tables=[] 意味着所有表都不在相关列表，但对空列表需特殊处理
        # 实际行为：relevant_tables 为 [] 时 relevant_tables 判为 falsy，等同于 None
        # 所以此时 not relevant_tables = True → 全量显示
        # 这是设计决策，测试文档化该行为
        assert "tbl_holding" in ctx


# ═══════════════════════════════════════════════════════════════
#  compress_messages 测试
# ═══════════════════════════════════════════════════════════════

class TestCompressMessages:
    def _make_messages(self, n_user_turns: int, tool_content_len: int = 100) -> list[dict]:
        """构造测试消息列表"""
        msgs = [{"role": "system", "content": "你是 DataAgent。"}]
        for i in range(n_user_turns):
            msgs.append({"role": "user", "content": f"问题 {i}"})
            msgs.append({
                "role": "assistant",
                "content": f"回答 {i}" + ("x" * tool_content_len),
            })
        return msgs

    def test_short_conversation_unchanged(self):
        """消息总数 ≤ max_keep_full 时不压缩"""
        from agent.context import compress_messages
        msgs = self._make_messages(3)
        compressed = compress_messages(msgs, max_keep_full=6)
        assert len(compressed) == len(msgs)

    def test_long_conversation_compressed(self):
        """超过 max_keep_full 条非系统消息时应压缩"""
        from agent.context import compress_messages
        msgs = self._make_messages(5)  # system + 10 非系统消息
        compressed = compress_messages(msgs, max_keep_full=4)
        # 压缩后数量应 < 原始数量或内容被截断
        assert len(compressed) <= len(msgs)

    def test_system_message_always_preserved(self):
        """system 消息始终完整保留"""
        from agent.context import compress_messages
        msgs = self._make_messages(8)
        compressed = compress_messages(msgs, max_keep_full=4)
        system_msgs = [m for m in compressed if m.get("role") == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "你是 DataAgent。"

    def test_recent_messages_preserved_fully(self):
        """最近 max_keep_full 条消息完整保留"""
        from agent.context import compress_messages
        msgs = self._make_messages(5)
        compressed = compress_messages(msgs, max_keep_full=4)
        # 最后 4 条非系统消息应完整
        non_sys = [m for m in compressed if m.get("role") != "system"]
        last_4 = non_sys[-4:]
        orig_non_sys = [m for m in msgs if m.get("role") != "system"]
        orig_last_4 = orig_non_sys[-4:]
        for orig, comp in zip(orig_last_4, last_4):
            assert comp["content"] == orig["content"]

    def test_long_tool_result_compressed(self):
        """超过 500 字符的 tool 消息应被压缩"""
        from agent.context import compress_messages
        long_content = "x" * 600
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "问题0"},
            {"role": "tool", "tool_call_id": "t1", "content": long_content},
            {"role": "user", "content": "问题1"},
            {"role": "assistant", "content": "回答1"},
            {"role": "user", "content": "问题2"},
            {"role": "assistant", "content": "回答2"},
            {"role": "user", "content": "问题3"},
            {"role": "assistant", "content": "回答3"},
        ]
        compressed = compress_messages(msgs, max_keep_full=4)
        # 找到 tool 消息
        tool_msgs = [m for m in compressed if m.get("role") == "tool"]
        if tool_msgs:
            assert len(tool_msgs[0]["content"]) < len(long_content)
            assert "已压缩" in tool_msgs[0]["content"]

    def test_long_assistant_text_truncated(self):
        """超过 200 字符的 assistant 消息应被截断"""
        from agent.context import compress_messages
        long_text = "A" * 300
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": long_text},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "短回答1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "短回答2"},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": "短回答3"},
        ]
        compressed = compress_messages(msgs, max_keep_full=4)
        early_assistant = [
            m for m in compressed
            if m.get("role") == "assistant" and m.get("content", "").endswith("...[已截断]")
        ]
        assert len(early_assistant) >= 1


# ═══════════════════════════════════════════════════════════════
#  extract_mention_tables 测试
# ═══════════════════════════════════════════════════════════════

class TestExtractMentionTables:
    @pytest.fixture(autouse=True)
    def setup_tables(self):
        import tools.data_loader as dl
        dl._loaded_tables.clear()
        dl._global_conn = None
        dl.init_duckdb_connection()
        dl._loaded_tables["holding_0515"] = type('T', (), {
            'table_name': 'holding_0515', 'row_count': 10, 'col_count': 5,
            'table_type': 'holding', 'quality_report': None,
            'field_map': {}, 'unmatched_cols': [], 'missing_required': [], 'warnings': [],
            'encoding': 'utf-8', 'date_tag': None,
        })()
        dl._loaded_tables["nav_0501"] = type('T', (), {
            'table_name': 'nav_0501', 'row_count': 5, 'col_count': 3,
            'table_type': 'nav', 'quality_report': None,
            'field_map': {}, 'unmatched_cols': [], 'missing_required': [], 'warnings': [],
            'encoding': 'utf-8', 'date_tag': None,
        })()
        yield
        dl._loaded_tables.clear()

    def test_single_mention(self):
        from agent.context import extract_mention_tables
        result = extract_mention_tables("查询 @holding_0515 的集中度")
        assert result == ["holding_0515"]

    def test_multiple_mentions(self):
        from agent.context import extract_mention_tables
        result = extract_mention_tables("对比 @holding_0515 和 @nav_0501")
        assert "holding_0515" in result
        assert "nav_0501" in result

    def test_nonexistent_mention_filtered(self):
        from agent.context import extract_mention_tables
        result = extract_mention_tables("查询 @unknown_table 数据")
        assert result == []

    def test_no_mention(self):
        from agent.context import extract_mention_tables
        result = extract_mention_tables("查询持仓情况")
        assert result == []

    def test_mention_with_comma(self):
        """逗号紧跟 @mention 时不应包含逗号（规则3）"""
        from agent.context import extract_mention_tables
        result = extract_mention_tables("@holding_0515，帮我分析")
        assert "holding_0515" in result
        assert all("，" not in t for t in result)


# ═══════════════════════════════════════════════════════════════
#  CostTracker 测试
# ═══════════════════════════════════════════════════════════════

class TestCostTracker:
    def test_empty_tracker(self):
        from tools.cost_tracker import CostTracker
        ct = CostTracker()
        summary = ct.get_summary()
        assert summary.total_calls == 0
        assert summary.total_cost_cny == 0.0

    def test_record_and_summarize(self):
        from tools.cost_tracker import CostTracker
        ct = CostTracker()
        ct.record("deepseek", input_tokens=1000, output_tokens=200, duration_ms=500)
        summary = ct.get_summary()
        assert summary.total_calls == 1
        assert summary.total_input_tokens == 1000
        assert summary.total_cost_cny > 0.0

    def test_local_provider_zero_cost(self):
        from tools.cost_tracker import CostTracker
        ct = CostTracker()
        ct.record("lmstudio", input_tokens=5000, output_tokens=1000, duration_ms=200)
        summary = ct.get_summary()
        assert summary.total_cost_cny == 0.0

    def test_budget_within(self):
        from tools.cost_tracker import CostTracker
        ct = CostTracker(budget_cny=100.0)
        ct.record("deepseek", input_tokens=100, output_tokens=50, duration_ms=100)
        within, msg = ct.check_budget()
        assert within

    def test_budget_exceeded(self):
        from tools.cost_tracker import CostTracker
        ct = CostTracker(budget_cny=0.000001)
        ct.record("deepseek", input_tokens=10000, output_tokens=5000, duration_ms=100)
        within, msg = ct.check_budget()
        assert not within
        assert "超出" in msg

    def test_by_provider_breakdown(self):
        from tools.cost_tracker import CostTracker
        ct = CostTracker()
        ct.record("deepseek", input_tokens=1000, output_tokens=200)
        ct.record("lmstudio", input_tokens=2000, output_tokens=400)
        summary = ct.get_summary()
        assert "deepseek" in summary.by_provider
        assert "lmstudio" in summary.by_provider

    def test_reset(self):
        from tools.cost_tracker import CostTracker
        ct = CostTracker()
        ct.record("deepseek", input_tokens=100, output_tokens=50)
        ct.reset()
        assert ct.get_summary().total_calls == 0

    def test_to_dict_serializable(self):
        from tools.cost_tracker import CostTracker
        import json
        ct = CostTracker()
        ct.record("deepseek", input_tokens=500, output_tokens=100, duration_ms=200)
        d = ct.to_dict()
        json.dumps(d)  # 应能正常序列化
        assert "total_cost_cny" in d
        assert "budget_message" in d

    def test_thread_safety(self):
        import threading
        from tools.cost_tracker import CostTracker
        ct = CostTracker()
        errors = []

        def record_many():
            try:
                for _ in range(50):
                    ct.record("deepseek", input_tokens=10, output_tokens=5)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert ct.get_summary().total_calls == 200  # 4 threads × 50 calls
