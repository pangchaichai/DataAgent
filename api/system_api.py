"""
api/system_api.py — 系统健康、状态、日志、LLM 路由
"""
from flask import Blueprint, jsonify, request

from session_store import BASE_DIR, _config_file_lock, _session, _session_lock

system_bp = Blueprint('system', __name__)


@system_bp.route('/api/health')
def api_health():
    try:
        import psutil
        proc = psutil.Process()
        ram_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        ram_mb = 0

    with _session_lock:
        turn = _session.get("turn_count", 0)

    llm_status = "online"
    llm_name = "deepseek-chat"
    llm_latency = 0

    try:
        from agent.llm_client import LLMClient
        client = LLMClient(str(BASE_DIR / 'config.yaml'))
        llm_name = client.sql_gen_cfg.get('model', 'deepseek-chat')
    except Exception:
        pass

    return jsonify({
        "llm_status": llm_status,
        "llm_name": llm_name,
        "llm_latency": llm_latency,
        "ram_mb": ram_mb,
        "token_used": 0,
        "token_limit": 64000,
        "turn_count": turn,
    })


@system_bp.route('/api/status')
def api_status():
    from tools.data_loader import get_loaded_tables
    tables = get_loaded_tables()
    llm_ok = True
    try:
        from agent.llm_client import LLMClient
        client = LLMClient(str(BASE_DIR / 'config.yaml'))
        key = client.sql_gen_cfg.get('api_key', '')
        llm_ok = bool(key and not key.startswith('sk-placeholder'))
    except Exception:
        llm_ok = False
    from datetime import date
    today = date.today().strftime("%Y%m%d")
    data_fresh = all(
        t.get('date_tag', '') == today
        for t in tables if t.get('date_tag')
    ) if tables else None
    return jsonify({
        "llm_ok": llm_ok,
        "tables_count": len(tables),
        "tables": tables,
        "data_fresh": data_fresh,
    })


@system_bp.route('/api/suggestions')
def api_suggestions():
    from tools.data_loader import get_loaded_tables
    tables = get_loaded_tables()
    types = {t['type'] for t in tables}
    suggestions = []
    if 'holding' in types:
        suggestions.append("查询各产品的主要持仓情况，按市值降序排列")
        suggestions.append("统计不同资产类别的持仓比例")
    if 'holding' in types:
        suggestions.append("检查主体集中度是否有超标情况，阈值10%")
    if 'nav' in types:
        suggestions.append("分析近期净值走势，计算区间收益率")
    if 'holding' in types and 'rating_entity' in types:
        suggestions.append("结合评级数据分析持仓信用分布")
    if not types:
        suggestions = [
            "上传持仓CSV文件开始分析",
            "查询持仓情况",
            "合规监控：主体集中度检查",
        ]
    return jsonify({"suggestions": suggestions[:5]})


@system_bp.route('/api/cost')
def api_cost():
    from tools.cost_tracker import get_cost_tracker
    return jsonify(get_cost_tracker().to_dict())


@system_bp.route('/api/logs')
def api_logs():
    from tools.runtime_logger import get_logger
    logger = get_logger()
    date_str = request.args.get('date', '')
    level = request.args.get('level', '')
    category = request.args.get('category', '')
    limit = min(int(request.args.get('limit', 200)), 1000)
    return jsonify({
        "entries": logger.read_logs(date_str, level, category, limit),
    })


@system_bp.route('/api/logs/files')
def api_log_files():
    from tools.runtime_logger import get_logger
    return jsonify({"files": get_logger().get_log_files()})


@system_bp.route('/api/logs/stats')
def api_log_stats():
    from tools.runtime_logger import get_logger
    return jsonify(get_logger().get_stats())


@system_bp.route('/api/logs/mode', methods=['POST'])
def api_log_mode():
    data = request.get_json(force=True) if request.is_json else {}
    mode = data.get('mode', '')
    if mode not in ('basic', 'detailed'):
        return jsonify({"ok": False, "error": "模式必须为 basic 或 detailed"}), 400

    import yaml

    from tools.runtime_logger import get_logger
    logger = get_logger()
    logger.mode = mode

    with _config_file_lock:
        cfg_path = BASE_DIR / 'config.yaml'
        src = cfg_path if cfg_path.exists() else BASE_DIR / 'config.example.yaml'
        try:
            with open(src, encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            cfg.setdefault('logging', {})['mode'] = mode
            tmp = cfg_path.with_suffix('.yaml.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                yaml.dump(cfg, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            tmp.replace(cfg_path)
        except Exception:
            pass

    return jsonify({"ok": True, "mode": mode})


@system_bp.route('/api/logs/cleanup', methods=['POST'])
def api_log_cleanup():
    from tools.runtime_logger import get_logger
    get_logger().cleanup_old_logs()
    return jsonify({"ok": True})


@system_bp.route('/api/llm/providers')
def api_llm_providers():
    try:
        from agent.llm_client import LLMClient
        client = LLMClient(str(BASE_DIR / 'config.yaml'))
        providers = client.list_providers()
        current = client.sql_gen_cfg.get('primary', 'enterprise_internal')
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"providers": providers, "current": current})


@system_bp.route('/api/llm/test', methods=['POST'])
def api_llm_test():
    data = request.get_json(silent=True) or {}
    provider = data.get('provider')
    try:
        from agent.llm_client import LLMClient
        client = LLMClient(str(BASE_DIR / 'config.yaml'))
        result = client.test_connection(provider)
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    return jsonify(result)
