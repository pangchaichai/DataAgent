"""
tests/test_hooks.py — HookManager 单元测试（I-5b）
"""

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  HookManager 核心测试
# ═══════════════════════════════════════════════════════════════

class TestHookManager:
    def setup_method(self):
        from agent.hooks import HookManager
        self.hm = HookManager()

    def test_register_valid_event(self):
        called = []
        self.hm.register("pre_tool_use", lambda ctx: called.append(ctx))
        self.hm.emit("pre_tool_use", {"tool": "run_sql"})
        assert len(called) == 1
        assert called[0]["tool"] == "run_sql"

    def test_register_invalid_event_ignored(self):
        result = self.hm.register("nonexistent_event", lambda ctx: None)
        assert result is False

    def test_emit_returns_nonnull_results(self):
        self.hm.register("post_tool_use", lambda ctx: ctx.get("ok"))
        results = self.hm.emit("post_tool_use", {"ok": True})
        assert results == [True]

    def test_emit_filters_none_results(self):
        self.hm.register("on_data_load", lambda ctx: None)
        results = self.hm.emit("on_data_load", {})
        assert results == []

    def test_hook_exception_isolated(self):
        """Hook 异常不阻塞后续 hook"""
        calls = []
        self.hm.register("on_error", lambda ctx: 1 / 0)  # raises
        self.hm.register("on_error", lambda ctx: calls.append("ok"))
        self.hm.emit("on_error", {})
        assert calls == ["ok"]

    def test_multiple_hooks_same_event(self):
        results = []
        self.hm.register("on_session_start", lambda ctx: results.append(1))
        self.hm.register("on_session_start", lambda ctx: results.append(2))
        self.hm.emit("on_session_start", {})
        assert results == [1, 2]

    def test_emit_unknown_event_returns_empty(self):
        results = self.hm.emit("unknown_event", {})
        assert results == []

    def test_emit_none_context_defaults_to_dict(self):
        received = []
        self.hm.register("on_agent_turn_end", lambda ctx: received.append(ctx))
        self.hm.emit("on_agent_turn_end")  # no context
        assert received == [{}]

    def test_unregister(self):
        calls = []
        cb = lambda ctx: calls.append(1)
        self.hm.register("pre_tool_use", cb)
        self.hm.unregister("pre_tool_use", cb)
        self.hm.emit("pre_tool_use", {})
        assert calls == []

    def test_clear_specific_event(self):
        calls = []
        self.hm.register("pre_tool_use", lambda ctx: calls.append("pre"))
        self.hm.register("post_tool_use", lambda ctx: calls.append("post"))
        self.hm.clear("pre_tool_use")
        self.hm.emit("pre_tool_use", {})
        self.hm.emit("post_tool_use", {})
        assert calls == ["post"]

    def test_clear_all(self):
        calls = []
        self.hm.register("pre_tool_use", lambda ctx: calls.append(1))
        self.hm.register("on_data_load", lambda ctx: calls.append(2))
        self.hm.clear()
        self.hm.emit("pre_tool_use", {})
        self.hm.emit("on_data_load", {})
        assert calls == []

    def test_thread_safety(self):
        """并发注册和触发不崩溃"""
        errors = []
        count = []

        def worker():
            try:
                cb = lambda ctx: count.append(1)
                self.hm.register("on_agent_turn_end", cb)
                for _ in range(20):
                    self.hm.emit("on_agent_turn_end", {})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ═══════════════════════════════════════════════════════════════
#  全局单例
# ═══════════════════════════════════════════════════════════════

def test_get_hook_manager_singleton():
    from agent.hooks import get_hook_manager
    hm1 = get_hook_manager()
    hm2 = get_hook_manager()
    assert hm1 is hm2


# ═══════════════════════════════════════════════════════════════
#  Compliance audit hash chain 测试
# ═══════════════════════════════════════════════════════════════

class TestComplianceHashChain:
    def test_first_record_has_seed_hash(self, tmp_path, monkeypatch):
        """首条记录 prev_hash 应等于种子哈希"""
        import hashlib
        from tools import compliance_audit as ca
        monkeypatch.setattr(ca, '_audit_dir', lambda: tmp_path)
        monkeypatch.setattr(ca, '_log_file', lambda: tmp_path / 'audit_test.jsonl')

        result = ca.log_compliance_event(
            event_type='monitoring', skill_name='test', data_files=[],
            sql_or_formula='', thresholds={}, result_summary={'count': 1},
        )
        assert result.ok

        events = ca.read_audit_log.__wrapped__(tmp_path / 'audit_test.jsonl') \
            if hasattr(ca.read_audit_log, '__wrapped__') else None
        # Read directly
        import json
        lines = (tmp_path / 'audit_test.jsonl').read_text().strip().split('\n')
        first = json.loads(lines[0])
        seed_hash = hashlib.sha256(ca._CHAIN_SEED.encode()).hexdigest()
        assert first['prev_hash'] == seed_hash

    def test_second_record_links_to_first(self, tmp_path, monkeypatch):
        """第二条记录 prev_hash 应等于第一条的 SHA256"""
        import hashlib, json
        from tools import compliance_audit as ca
        monkeypatch.setattr(ca, '_audit_dir', lambda: tmp_path)
        monkeypatch.setattr(ca, '_log_file', lambda: tmp_path / 'audit_chain.jsonl')

        ca.log_compliance_event('monitoring', 's1', [], '', {}, {'x': 1})
        ca.log_compliance_event('monitoring', 's2', [], '', {}, {'x': 2})

        lines = (tmp_path / 'audit_chain.jsonl').read_text().strip().split('\n')
        assert len(lines) == 2
        first_hash = hashlib.sha256(lines[0].encode()).hexdigest()
        second = json.loads(lines[1])
        assert second['prev_hash'] == first_hash
