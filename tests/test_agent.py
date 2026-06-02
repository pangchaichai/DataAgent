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

    def test_report_text_with_deepseek(self, client):
        """测试环境：DeepSeek 配置正确时 generate_report_text 应成功"""
        text, resp = client.generate_report_text(
            '生成报告摘要', {'净值': 1.05}
        )
        assert resp.success, f"DeepSeek 应可用: {resp.error}"

    def test_sql_gen_with_deepseek(self, client):
        """测试环境：DeepSeek 配置正确时 generate_sql 应返回 SQL"""
        sql, resp = client.generate_sql('查询持仓表所有记录')
        assert resp is not None
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
        from agent.loop import run_agent_loop
        import tools.data_loader as dl
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
        from agent.loop import run_agent_loop
        import tools.data_loader as dl
        dl._global_conn = None
        dl._loaded_tables.clear()
        dl.init_duckdb_connection()

        llm_client, skill_loader = self._get_components()
        events = list(run_agent_loop('查询持仓', llm_client, skill_loader))
        assert events[-1]['type'] == 'stream_end'
