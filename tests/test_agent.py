"""
tests/test_agent.py — Agent 层单元测试

覆盖：llm_client, skill_loader, loop（逐步扩展）
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  llm_client 测试
# ═══════════════════════════════════════════════════════════════

class TestLLMClient:
    """LLMClient 功能测试（不依赖真实 LLM 端点）"""

    @pytest.fixture
    def client(self):
        from agent.llm_client import LLMClient
        return LLMClient('config.yaml')

    def test_init_reads_config(self, client):
        """验证客户端能正确读取配置文件"""
        assert client.sql_gen_cfg is not None
        assert client.report_cfg is not None
        assert 'enterprise_internal' in client.providers
        assert 'deepseek' in client.providers

    def test_extract_sql_plain(self, client):
        """纯 SQL 文本应原样返回"""
        sql = 'SELECT * FROM t LIMIT 10'
        assert client._extract_sql(sql) == sql

    def test_extract_sql_markdown_fenced(self, client):
        """```sql ... ``` 包裹的应正确提取"""
        text = '```sql\nSELECT * FROM t LIMIT 10\n```'
        assert client._extract_sql(text) == 'SELECT * FROM t LIMIT 10'

    def test_extract_sql_markdown_no_lang(self, client):
        """``` ... ``` 无语言标注的也应正确提取"""
        text = '```\nSELECT 1\n```'
        assert client._extract_sql(text) == 'SELECT 1'

    def test_extract_sql_whitespace_trim(self, client):
        """首尾空白应被去除"""
        assert client._extract_sql('  SELECT 1  ') == 'SELECT 1'

    def test_report_text_degraded_when_no_api_key(self, client):
        """API key 为占位符时，report_text 应降级返回 ReportDegradedResult，不调用外部 LLM"""
        from agent.llm_client import ReportDegradedResult
        text, resp = client.generate_report_text(
            '生成报告摘要', {'净值': 1.05}
        )
        # 占位符 key → 应走降级路径，不抛异常
        assert isinstance(resp, ReportDegradedResult) or not resp.success, \
            "占位符 key 应触发降级或返回 success=False，不应成功调用外部 LLM"

    def test_sql_gen_placeholder_key_returns_error(self, client):
        """API key 为占位符时，generate_sql 应返回 success=False，error='api_key'"""
        sql, resp = client.generate_sql('查询持仓表所有记录')
        assert resp is not None
        # 占位符 key → 被拒，不调用外部
        assert not resp.success
        assert resp.error == 'api_key'

    @pytest.mark.skipif(
        not os.environ.get('DEEPSEEK_API_KEY'),
        reason="需要真实 DEEPSEEK_API_KEY 环境变量"
    )
    def test_sql_gen_with_real_api(self, client):
        """实际 API key 时 generate_sql 应返回 SQL（CI 环境跳过）"""
        sql, resp = client.generate_sql('查询持仓表所有记录')
        assert resp.success, f"SQL 生成应成功: {resp.error}"

    def test_classify_intent_no_skills(self, client):
        """无 Skill 注册表时应返回 None"""
        name, resp = client.classify_intent('查询持仓', [])
        assert name is None

    def test_classify_intent_empty_input(self, client):
        """空输入应正常处理"""
        name, resp = client.classify_intent('', [
            {'name': 'position_query', 'description': '持仓查询'}
        ])
        assert isinstance(name, (str, type(None)))


# ═══════════════════════════════════════════════════════════════
#  skill_loader 测试
# ═══════════════════════════════════════════════════════════════

class TestSkillLoader:
    """SkillLoader 功能测试（使用真实 skills/ 目录）"""

    @pytest.fixture
    def loader(self):
        from agent.skill_loader import SkillLoader
        return SkillLoader(local_dir='skills/')

    def test_load_registry(self, loader):
        """应能加载所有 8 个 Skill"""
        registry = loader.load_registry()
        assert len(registry) >= 8
        names = {s.name for s in registry}
        assert 'position_query' in names
        assert 'concentration_monitor' in names
        assert 'flexible_stats' in names

    def test_registry_has_required_fields(self, loader):
        """每个 SkillInfo 应有 name 和 description"""
        registry = loader.load_registry()
        for s in registry:
            assert s.name
            assert s.description
            assert s.calc_type in ('fixed', 'exploratory')

    def test_fixed_skill_has_calculator(self, loader):
        """calc_type=fixed 的 Skill 应有 fixed_calculator"""
        registry = loader.load_registry()
        for s in registry:
            if s.calc_type == 'fixed':
                assert s.fixed_calculator, f"{s.name} 缺少 fixed_calculator"

    def test_load_full(self, loader):
        """按需加载应返回完整 Markdown 内容"""
        content = loader.load_full('concentration_monitor')
        assert content is not None
        assert len(content) > 500
        assert 'calc_entity_concentration' in content

    def test_load_full_cache(self, loader):
        """两次加载同一 Skill 应命中缓存"""
        c1 = loader.load_full('position_query')
        c2 = loader.load_full('position_query')
        assert c1 is c2

    def test_load_full_nonexistent(self, loader):
        """不存在的 Skill 应返回 None"""
        assert loader.load_full('nonexistent_skill') is None

    def test_detect_position_query(self, loader):
        """持仓查询意图应匹配 position_query"""
        registry = loader.load_registry()
        result = loader.detect_relevant_skill('查询XX产品持仓情况', registry)
        assert result == 'position_query'

    def test_detect_concentration(self, loader):
        """集中度监控意图应匹配 concentration_monitor"""
        registry = loader.load_registry()
        result = loader.detect_relevant_skill('检查集中度是否超标', registry)
        assert result == 'concentration_monitor'

    def test_detect_no_match(self, loader):
        """无关输入应返回 None（探索式查询）"""
        registry = loader.load_registry()
        result = loader.detect_relevant_skill('今天天气怎么样', registry)
        assert result is None

    def test_detect_flexible_stats(self, loader):
        """统计意图应匹配 flexible_stats（含触发词：统计/汇总）"""
        registry = loader.load_registry()
        result = loader.detect_relevant_skill('按资产类型做分类统计汇总', registry)
        assert result == 'flexible_stats'


# ═══════════════════════════════════════════════════════════════
#  Agent Loop 测试
# ═══════════════════════════════════════════════════════════════

class TestCategorizeError:
    """错误分类函数测试"""

    def test_syntax_error(self):
        from agent.loop import categorize_tool_error
        assert categorize_tool_error('syntax error at line 5') == 'syntax'

    def test_semantic_column_error(self):
        from agent.loop import categorize_tool_error
        result = categorize_tool_error('Binder Error: No such column "product_name"')
        assert result == 'semantic'

    def test_semantic_table_error(self):
        from agent.loop import categorize_tool_error
        assert categorize_tool_error('referenced table not loaded: unknown_table') == 'semantic'

    def test_empty_result(self):
        from agent.loop import categorize_tool_error
        assert categorize_tool_error('no rows returned') == 'empty'

    def test_anomaly(self):
        from agent.loop import categorize_tool_error
        assert categorize_tool_error('unknown catastrophic failure') == 'anomaly'

    def test_parser_error_is_syntax(self):
        from agent.loop import categorize_tool_error
        assert categorize_tool_error('Parser Error: unexpected token "FROM"') == 'syntax'


class TestAgentLoopBasic:
    """Agent 循环基础测试"""

    @staticmethod
    def _get_components():
        from agent.llm_client import LLMClient
        from agent.skill_loader import SkillLoader
        return LLMClient('config.yaml'), SkillLoader(local_dir='skills/')

    def test_loop_no_tables_yields_help(self):
        import tools.data_loader as dl
        from agent.loop import run_agent_loop
        dl._global_conn = None
        dl._loaded_tables.clear()
        dl.init_duckdb_connection()

        llm_client, skill_loader = self._get_components()
        events = list(run_agent_loop('查询持仓', llm_client, skill_loader))
        assert len(events) >= 2
        assert events[0]['type'] == 'text'
        assert '上传' in str(events[0]['data'])

    def test_loop_max_turns(self):
        from agent.loop import run_agent_loop
        llm_client, skill_loader = self._get_components()
        events = list(run_agent_loop('查询', llm_client, skill_loader, turn_count=15))
        assert events[0]['type'] == 'error'

    def test_loop_yields_stream_end(self):
        import tools.data_loader as dl
        from agent.loop import run_agent_loop
        dl._global_conn = None
        dl._loaded_tables.clear()
        dl.init_duckdb_connection()

        llm_client, skill_loader = self._get_components()
        events = list(run_agent_loop('查询持仓', llm_client, skill_loader))
        assert events[-1]['type'] == 'stream_end'


# ═══════════════════════════════════════════════════════════════
#  Phase R1 新增测试：tool-calling loop
# ═══════════════════════════════════════════════════════════════

class MockChatLLM:
    """Mock LLMClient 用于测试 tool-calling loop"""

    def __init__(self, responses: list = None):
        from agent.llm_client import ChatResult
        self.responses = responses or []
        self.call_count = 0
        self.messages_log: list[list[dict]] = []

    def chat(self, messages, tools=None, timeout=None, max_tokens=None):
        from agent.llm_client import ChatResult
        self.messages_log.append(list(messages))
        if self.call_count < len(self.responses):
            result = self.responses[self.call_count]
            self.call_count += 1
            return result
        return ChatResult(success=True, text="最终回答", tool_calls=[])


def _make_chat_result(text="", tool_calls=None):
    """快捷构造 ChatResult"""
    from agent.llm_client import ChatResult
    return ChatResult(
        success=True, text=text,
        tool_calls=tool_calls or [],
        elapsed_ms=100, token_count=50, model="mock",
    )


def _make_tool_call(name, args, tc_id=""):
    """快捷构造 tool_call dict"""
    import uuid
    return {
        "id": tc_id or f"call_{uuid.uuid4().hex[:8]}",
        "name": name,
        "arguments": args,
    }


def _setup_test_holding_table():
    """创建一张最小持仓测试表"""
    import duckdb

    import tools.data_loader as dl
    dl._global_conn = None
    dl._loaded_tables.clear()
    conn = dl.init_duckdb_connection()
    conn.execute("""
        CREATE TABLE test_holding AS SELECT * FROM (VALUES
            ('产品A', '象屿集团', 1234567.89, 'AAA'),
            ('产品B', '建发集团', 2345678.90, 'AA+'),
            ('产品A', '国贸集团', 3456789.01, 'AA'),
        ) AS t("产品名称", "限额占用方主体", "穿透后市值", "外部评级")
    """)
    dl._loaded_tables["test_holding"] = type('obj', (object,), {
        'table_name': 'test_holding',
        'row_count': 3,
        'col_count': 4,
        'encoding': 'utf-8',
        'date_tag': None,
        'field_map': {
            '产品名称': '产品名称',
            '限额占用主体': '限额占用方主体',
            '穿透后市值': '穿透后市值',
            '外部评级': '外部评级',
        },
        'unmatched_cols': [],
        'missing_required': [],
        'warnings': [],
        'table_type': 'holding',
        'quality_report': None,  # ★R2
    })()
    return conn


class TestToolCallingLoop:
    """R1: tool-calling Agent 循环测试"""

    @staticmethod
    def _get_skill_loader():
        from agent.skill_loader import SkillLoader
        return SkillLoader(local_dir='skills/')

    def test_loop_multistep_runs_tools(self):
        """验证多步 tool-calling 事件顺序正确"""
        conn = _setup_test_holding_table()
        skill_loader = self._get_skill_loader()

        # Mock LLM: profile_table → run_sql → 最终回答
        mock = MockChatLLM([
            _make_chat_result(text="让我先看看表结构",
                tool_calls=[_make_tool_call("profile_table",
                    {"table_name": "test_holding"}, "tc1")]),
            _make_chat_result(text="现在查询数据",
                tool_calls=[_make_tool_call("run_sql",
                    {"sql": "SELECT * FROM test_holding LIMIT 10",
                     "purpose": "查看全部数据"}, "tc2")]),
            _make_chat_result(text="查询结果如上。", tool_calls=[]),
        ])

        from agent.loop import run_agent_loop
        events = list(run_agent_loop("分析这张表", mock, skill_loader))

        # 断言事件顺序
        event_types = [e['type'] for e in events]
        assert 'tool_start' in event_types
        assert 'tool_end' in event_types
        assert 'text' in event_types
        assert event_types[-1] == 'stream_end'

        # LLM 应被调用了3次
        assert mock.call_count == 3

    def test_loop_calculator_path(self):
        """验证 run_calculator 路径正确执行"""
        conn = _setup_test_holding_table()
        skill_loader = self._get_skill_loader()

        mock = MockChatLLM([
            _make_chat_result(text="这是合规场景，用固化计算",
                tool_calls=[_make_tool_call("run_calculator",
                    {"calculator": "entity_concentration",
                     "holding_table": "test_holding"}, "tc1")]),
            _make_chat_result(text="集中度计算完成，无超标。", tool_calls=[]),
        ])

        from agent.loop import run_agent_loop
        events = list(run_agent_loop("检查集中度是否超标", mock, skill_loader))

        # 应有 tool_start for run_calculator
        tool_starts = [e for e in events if e['type'] == 'tool_start']
        assert any('run_calculator' in str(e['data']) for e in tool_starts), \
            f"Expected run_calculator tool_start, got: {tool_starts}"

        # 应正常结束
        assert events[-1]['type'] == 'stream_end'

    def test_loop_ask_user_pause_resume(self):
        """验证 ask_user 暂停 → 保存 pending → 续跑"""
        conn = _setup_test_holding_table()
        skill_loader = self._get_skill_loader()

        # 第一次：ask_user 暂停
        mock1 = MockChatLLM([
            _make_chat_result(text="需要确认",
                tool_calls=[_make_tool_call("ask_user",
                    {"question": "用穿透后还是半穿透口径？",
                     "options": ["穿透后", "半穿透"]}, "tc_ask")]),
        ])

        from agent.loop import run_agent_loop
        events1 = list(run_agent_loop(
            "查集中度", mock1, skill_loader,
            session_messages=None, pending=None,
        ))

        # 应有 ask 事件
        ask_events = [e for e in events1 if e['type'] == 'ask']
        assert len(ask_events) == 1
        assert '穿透后' in str(ask_events[0]['data'])

        # 应有 __pending__ 事件
        pending_events = [e for e in events1 if e['type'] == '__pending__']
        assert len(pending_events) == 1
        pending = pending_events[0]['data']
        assert pending['type'] == 'ask'
        assert pending['tool_call_id'] == 'tc_ask'

        # 续跑：用户回答，传入 pending
        mock2 = MockChatLLM([
            _make_chat_result(text="好的，用穿透后口径计算。", tool_calls=[]),
        ])

        # 重建 session_messages（从 events1 中提取消息无法做到，用简化方式）
        msgs = [
            {"role": "system", "content": "你是 DataAgent。"},
            {"role": "user", "content": "查集中度"},
            {"role": "assistant", "content": "需要确认", "tool_calls": [
                {"id": "tc_ask", "type": "function",
                 "function": {"name": "ask_user", "arguments": '{"question":"用穿透后还是半穿透口径？","options":["穿透后","半穿透"]}'}}
            ]},
        ]

        events2 = list(run_agent_loop(
            "穿透后", mock2, skill_loader,
            session_messages=msgs,
            pending=pending,
        ))

        # 应正常结束
        assert events2[-1]['type'] == 'stream_end'
        # 不应再有 ask 事件（已续跑）
        assert not any(e['type'] == 'ask' for e in events2)

    def test_no_llm_sql_for_compliance(self):
        """合规路径不应让 LLM 生成的 SQL 进入 query_runner"""
        conn = _setup_test_holding_table()
        skill_loader = self._get_skill_loader()

        # run_calculator 使用固化公式，不经过 query_runner
        mock = MockChatLLM([
            _make_chat_result(text="合规场景，用固化计算",
                tool_calls=[_make_tool_call("run_calculator",
                    {"calculator": "entity_concentration"}, "tc1")]),
            _make_chat_result(text="完成。", tool_calls=[]),
        ])

        from agent.loop import run_agent_loop
        events = list(run_agent_loop("集中度超标了吗", mock, skill_loader))

        # 不应该有 run_sql 的 tool_start
        sql_starts = [e for e in events if e['type'] == 'tool_start'
                      and e['data'].get('tool') == 'run_sql']
        assert len(sql_starts) == 0, "合规路径不应调用 run_sql"

        # 应有 run_calculator 的 tool_start
        calc_starts = [e for e in events if e['type'] == 'tool_start'
                       and e['data'].get('tool') == 'run_calculator']
        assert len(calc_starts) >= 1

    def test_multiturn_memory(self):
        """两次连续消息：第二条应带上第一条的上下文"""
        conn = _setup_test_holding_table()
        skill_loader = self._get_skill_loader()

        # 第一轮对话 — 传入空列表，loop 会往里追加消息
        session_msgs: list[dict] = []

        mock1 = MockChatLLM([
            _make_chat_result(text="A产品的集中度是5%，未超标。", tool_calls=[]),
        ])

        from agent.loop import run_agent_loop
        events1 = list(run_agent_loop(
            "A产品集中度怎么样", mock1, skill_loader,
            session_messages=session_msgs, pending=None,
        ))
        assert events1[-1]['type'] == 'stream_end'
        # loop 结束后 session_msgs 应被更新（含 system + user + assistant）
        assert len(session_msgs) >= 3, f"Expected >=3 msgs, got {len(session_msgs)}: {[m.get('role') for m in session_msgs]}"

        # 第二轮对话（带历史消息）
        mock2 = MockChatLLM([
            _make_chat_result(text="B产品集中度是3%，也未超标。", tool_calls=[]),
        ])

        events2 = list(run_agent_loop(
            "那B产品呢", mock2, skill_loader,
            session_messages=session_msgs,  # 同一列表引用，含第一轮历史
            pending=None,
        ))
        assert events2[-1]['type'] == 'stream_end'

        # 第二轮传给 LLM 的消息应包含第一轮的上下文
        msgs_round2 = mock2.messages_log[0] if mock2.messages_log else []
        roles = [m.get('role') for m in msgs_round2]
        assert 'system' in roles
        # 至少应有 4 条消息（system + round1 user + round1 assistant + round2 user）
        # round2 assistant 是 chat() 返回后才追加的，不在 messages_log 中
        assert len(msgs_round2) >= 4, \
            f"Expected >=4 msgs, got {len(msgs_round2)}: {roles}"


# ═══════════════════════════════════════════════════════════════
#  Phase R4 新增：内联推断测试
# ═══════════════════════════════════════════════════════════════

class TestSchemaInference:
    """R4: 未知表内联推断"""

    def test_sanitize_samples(self):
        """外网脱敏应替换实际值为占位符"""
        from tools.profiler import _sanitize_samples
        raw = ["厦门象屿集团有限公司", "建发集团"]
        result = _sanitize_samples(raw, "限额占用主体")
        assert "厦门象屿" not in str(result)
        assert "[实体" in str(result[0])

    def test_propose_dict_is_draft_only(self):
        """propose_dict_entry 只写 drafts/，不改正式字典"""
        from pathlib import Path

        import yaml

        from agent.tools_spec import ToolContext, _tool_propose_dict_entry

        ctx = ToolContext()
        # 写入测试草稿
        result = _tool_propose_dict_entry({
            "table_type": "test_type",
            "semantic_name": "测试市值",
            "physical_column": "test_mkt_val",
        }, ctx)
        assert result["ok"]

        # 验证只在 drafts/
        drafts_dir = Path(__file__).resolve().parent.parent / "data_dictionary" / "drafts"
        draft_file = drafts_dir / "test_type_draft.yaml"
        assert draft_file.exists()

        # 清理
        draft_file.unlink(missing_ok=True)

    def test_confirm_dict_merges_draft(self):
        """confirm_dict 应合并草稿到正式字典"""
        from pathlib import Path

        import yaml

        from agent.tools_spec import ToolContext, _tool_confirm_dict, _tool_propose_dict_entry

        ctx = ToolContext()
        # 先写草稿
        _tool_propose_dict_entry({
            "table_type": "holding",
            "semantic_name": "测试字段_R4",
            "physical_column": "test_col",
        }, ctx)

        # 确认入库（到正式 dict）
        result = _tool_confirm_dict({"table_type": "holding"}, ctx)
        assert result["ok"]

        # 验证已合并
        dict_file = Path(__file__).resolve().parent.parent / "data_dictionary" / "holding_dict.yaml"
        with open(dict_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        semantics = [f["semantic"] for f in data.get("fields", [])]
        assert "测试字段_R4" in semantics

        # 清理：从正式字典中移除测试字段
        data["fields"] = [f for f in data.get("fields", []) if f["semantic"] != "测试字段_R4"]
        with open(dict_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


# ═══════════════════════════════════════════════════════════════
#  Phase R5 新增：收窄版记忆
# ═══════════════════════════════════════════════════════════════

class TestAgentMemory:
    """R5: scoped cross-session memory"""

    def test_memory_disabled_noop(self, tmp_path):
        """关闭时 save_correction 应不做任何事"""
        from agent.memory import AgentMemory
        db = tmp_path / "test.db"
        mem = AgentMemory(str(db), enabled=False)
        mem.initialize()
        mem.save_correction("市值-holding", "用穿透后")
        # 数据库不应被创建
        assert not db.exists()

    def test_memory_enabled_save_recall(self, tmp_path):
        """开启后保存和召回应正常工作"""
        from agent.memory import AgentMemory
        db = tmp_path / "test.db"
        mem = AgentMemory(str(db), enabled=True)
        mem.initialize()
        mem.save_correction("市值字段-holding", "使用穿透后市值而非账面市值")
        mem.save_correction("产品名称-nav", "产品简称对应产品名称")

        results = mem.recall("市值")
        assert len(results) >= 1
        assert any("穿透后" in r["content"] for r in results)

        # 清理
        mem._conn.close()
        db.unlink(missing_ok=True)

    def test_memory_empty_recall(self, tmp_path):
        """空记忆库召回应返回空列表"""
        from agent.memory import AgentMemory
        db = tmp_path / "test_empty.db"
        mem = AgentMemory(str(db), enabled=True)
        mem.initialize()
        results = mem.recall("任何查询")
        assert results == []
        mem._conn.close()
        db.unlink(missing_ok=True)

    def test_memory_no_sql_pattern(self):
        """不应有 sql_pattern/business_rule 写入路径"""
        from agent.memory import AgentMemory
        mem = AgentMemory(enabled=True)
        # 验证类只有 save_correction 一个写方法
        write_methods = [m for m in dir(mem) if m.startswith('save')]
        assert 'save_correction' in write_methods
        assert 'save_sql' not in write_methods
        assert 'save_business_rule' not in write_methods


# ═══════════════════════════════════════════════════════════════
#  I-1b 新增：参数校验 + 工具过滤测试（ETCLOVG T 层）
# ═══════════════════════════════════════════════════════════════

class TestToolArgValidation:
    """_validate_tool_args：入参校验逻辑"""

    def test_profile_table_missing_required(self):
        from agent.tools_spec import _validate_tool_args
        ok, err = _validate_tool_args("profile_table", {})
        assert not ok
        assert "table_name" in err

    def test_profile_table_valid(self):
        from agent.tools_spec import _validate_tool_args
        ok, err = _validate_tool_args("profile_table", {"table_name": "test"})
        assert ok

    def test_run_sql_missing_sql(self):
        from agent.tools_spec import _validate_tool_args
        ok, err = _validate_tool_args("run_sql", {"purpose": "test"})
        assert not ok
        assert "sql" in err

    def test_run_sql_valid_without_purpose(self):
        """purpose 是可选字段，仅有 sql 应通过"""
        from agent.tools_spec import _validate_tool_args
        ok, _ = _validate_tool_args("run_sql", {"sql": "SELECT 1"})
        assert ok

    def test_run_sql_valid(self):
        from agent.tools_spec import _validate_tool_args
        ok, _ = _validate_tool_args("run_sql", {
            "sql": "SELECT * FROM t LIMIT 10",
            "purpose": "测试查询",
        })
        assert ok

    def test_run_calculator_missing_calculator(self):
        from agent.tools_spec import _validate_tool_args
        ok, err = _validate_tool_args("run_calculator", {"holding_table": "t"})
        assert not ok
        assert "calculator" in err

    def test_run_calculator_invalid_enum(self):
        from agent.tools_spec import _validate_tool_args
        ok, err = _validate_tool_args("run_calculator", {
            "calculator": "nonexistent_calc",
            "holding_table": "t",
        })
        assert not ok
        assert "calculator" in err.lower() or "enum" in err.lower() or "nonexistent" in err.lower()

    def test_run_calculator_valid_enum(self):
        from agent.tools_spec import _validate_tool_args
        ok, _ = _validate_tool_args("run_calculator", {
            "calculator": "entity_concentration",
            "holding_table": "test_holding",
        })
        assert ok

    def test_ask_user_missing_question(self):
        from agent.tools_spec import _validate_tool_args
        ok, err = _validate_tool_args("ask_user", {"options": ["A", "B"]})
        assert not ok
        assert "question" in err

    def test_ask_user_valid_without_options(self):
        """options 是可选字段，仅有 question 应通过"""
        from agent.tools_spec import _validate_tool_args
        ok, _ = _validate_tool_args("ask_user", {"question": "选哪个？"})
        assert ok

    def test_unknown_tool_passes(self):
        """未知工具名称：无 schema 可校验，应通过"""
        from agent.tools_spec import _validate_tool_args
        ok, _ = _validate_tool_args("unknown_tool", {"x": 1})
        assert ok


class TestToolFiltering:
    """_filter_tools_for_context：场景化工具过滤"""

    def test_exploratory_skill_keeps_run_sql(self):
        from agent.loop import _filter_tools_for_context
        from agent.skill_loader import SkillInfo
        from agent.tools_spec import TOOL_DEFINITIONS
        skill = SkillInfo(name="flexible_stats", description="灵活统计",
                          calc_type="exploratory")
        filtered = _filter_tools_for_context(TOOL_DEFINITIONS, skill)
        names = [t["function"]["name"] for t in filtered]
        assert "run_sql" in names

    def test_fixed_skill_removes_run_sql(self):
        from agent.loop import _filter_tools_for_context
        from agent.skill_loader import SkillInfo
        from agent.tools_spec import TOOL_DEFINITIONS
        skill = SkillInfo(name="concentration_monitor", description="集中度监控",
                          calc_type="fixed")
        filtered = _filter_tools_for_context(TOOL_DEFINITIONS, skill)
        names = [t["function"]["name"] for t in filtered]
        assert "run_sql" not in names
        assert "run_calculator" in names

    def test_no_skill_keeps_all_tools(self):
        from agent.loop import _filter_tools_for_context
        from agent.tools_spec import TOOL_DEFINITIONS
        filtered = _filter_tools_for_context(TOOL_DEFINITIONS, None)
        assert len(filtered) == len(TOOL_DEFINITIONS)

    def test_fixed_skill_loop_filters_run_sql(self):
        """端到端：Loop 匹配 fixed skill 后，传给 LLM 的工具不含 run_sql"""
        conn = _setup_test_holding_table()
        from agent.skill_loader import SkillLoader
        skill_loader = SkillLoader(local_dir='skills/')

        received_tools: list = []

        class ToolCapturingLLM:
            call_count = 0

            def chat(self, messages, tools=None, timeout=None, max_tokens=None):
                from agent.llm_client import ChatResult
                received_tools.extend(tools or [])
                self.call_count += 1
                return ChatResult(success=True, text="完成", tool_calls=[])

        mock = ToolCapturingLLM()

        from agent.loop import run_agent_loop
        list(run_agent_loop("检查集中度是否超标", mock, skill_loader))

        tool_names = [t["function"]["name"] for t in received_tools]
        # concentration_monitor 是 fixed skill，run_sql 应被过滤
        assert "run_sql" not in tool_names, (
            f"Fixed skill 场景不应暴露 run_sql，实际工具：{tool_names}"
        )
