"""
api/config_api.py — 配置、集团管理、任务、记忆路由
"""
from flask import Blueprint, jsonify, request

from session_store import BASE_DIR, _config_file_lock

config_bp = Blueprint('config', __name__)


@config_bp.route('/api/config')
def api_config_read():
    import yaml
    cfg_path = BASE_DIR / 'config.yaml'
    src = cfg_path if cfg_path.exists() else BASE_DIR / 'config.example.yaml'
    try:
        with open(src, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        return jsonify({"error": f"读取配置失败：{e}"}), 500
    llm_cfg = cfg.get('llm', {})
    primary = llm_cfg.get('sql_gen', {}).get('primary', 'deepseek')
    provider_cfg = llm_cfg.get(primary, llm_cfg.get('deepseek', {}))
    raw_key = provider_cfg.get('api_key', '')
    api_key_set = bool(raw_key and raw_key not in (
        '', '你的DeepSeek_API_Key', '${DEEPSEEK_API_KEY}'
    ))
    return jsonify({
        "user_profile": cfg.get('user_profile', {}),
        "calculation_config": cfg.get('calculation_config', {}),
        "memory": cfg.get('memory', {"enabled": False}),
        "scheduler": cfg.get('scheduler', {"enabled": True}),
        "app": cfg.get('app', {}),
        "api_key_set": api_key_set,
        "llm_url": provider_cfg.get('url', ''),
        "llm_model": provider_cfg.get('model', 'deepseek-chat'),
        "llm_provider": primary,
        "logging": cfg.get('logging', {"mode": "basic", "max_days": 30}),
    })


@config_bp.route('/api/config', methods=['POST'])
def api_config_write():
    import yaml
    data = request.get_json(force=True) if request.is_json else {}
    cfg_path = BASE_DIR / 'config.yaml'
    with _config_file_lock:
        src = cfg_path if cfg_path.exists() else BASE_DIR / 'config.example.yaml'
        try:
            with open(src, encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}
        if 'user_profile' in data:
            cfg.setdefault('user_profile', {})
            for field in ('name', 'department', 'role', 'managed_products'):
                if field in data['user_profile']:
                    cfg['user_profile'][field] = data['user_profile'][field]
        if 'calculation_config' in data:
            cfg.setdefault('calculation_config', {})
            cc = data['calculation_config']
            if 'concentration' in cc:
                cfg['calculation_config'].setdefault('concentration', {})
                for field in ('threshold_entity', 'threshold_single_bond',
                              'market_value_field', 'use_group_merge', 'data_max_age_days'):
                    if field in cc['concentration']:
                        cfg['calculation_config']['concentration'][field] = cc['concentration'][field]
        if 'memory' in data and 'enabled' in data['memory']:
            cfg.setdefault('memory', {})['enabled'] = bool(data['memory']['enabled'])
        if 'scheduler' in data and 'enabled' in data['scheduler']:
            cfg.setdefault('scheduler', {})['enabled'] = bool(data['scheduler']['enabled'])
        if data.get('llm_url') or data.get('llm_model') or data.get('api_key') or data.get('llm_provider'):
            llm_block = cfg.setdefault('llm', {})
            if data.get('llm_provider'):
                llm_block.setdefault('sql_gen', {})['primary'] = data['llm_provider']
            primary = llm_block.get('sql_gen', {}).get('primary', 'deepseek')
            provider_block = llm_block.setdefault(primary, {})
            if data.get('api_key'):
                provider_block['api_key'] = data['api_key']
            if data.get('llm_url'):
                provider_block['url'] = data['llm_url']
            if data.get('llm_model'):
                provider_block['model'] = data['llm_model']
        try:
            tmp_path = cfg_path.with_suffix('.yaml.tmp')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                yaml.dump(cfg, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            tmp_path.replace(cfg_path)
        except Exception as e:
            return jsonify({"ok": False, "error": f"写入配置失败：{e}"}), 500
    return jsonify({"ok": True})


@config_bp.route('/api/groups')
def api_groups():
    from tools.entity_manager import EntityManager
    mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
    return jsonify({"groups": mgr.list_groups()})


@config_bp.route('/api/groups', methods=['POST'])
def api_create_group():
    data = request.get_json(force=True) if request.is_json else {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"ok": False, "error": "集团名称不能为空"}), 400
    from tools.entity_manager import EntityManager
    mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
    try:
        mgr.create_group(name, data.get('members', []))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@config_bp.route('/api/groups/<name>/members', methods=['POST'])
def api_add_member(name):
    data = request.get_json(force=True) if request.is_json else {}
    entity = (data.get('entity') or '').strip()
    if not entity:
        return jsonify({"ok": False, "error": "主体名称不能为空"}), 400
    from tools.entity_manager import EntityManager
    mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
    try:
        mgr.add_member(name, entity)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@config_bp.route('/api/groups/<name>/members', methods=['DELETE'])
def api_remove_member(name):
    data = request.get_json(force=True) if request.is_json else {}
    entity_name = (data.get('entity') or '').strip()
    if not entity_name:
        return jsonify({"ok": False, "error": "主体名称不能为空"}), 400
    from tools.entity_manager import EntityManager
    mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
    try:
        mgr.remove_member(name, entity_name)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@config_bp.route('/api/groups/<name>', methods=['DELETE'])
def api_delete_group(name):
    from tools.entity_manager import EntityManager
    mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
    try:
        mgr.delete_group(name)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@config_bp.route('/api/tasks')
def api_tasks():
    import yaml
    tasks_path = BASE_DIR / 'tasks' / 'task_config.yaml'
    if not tasks_path.exists():
        return jsonify({"tasks": []})
    try:
        with open(tasks_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        return jsonify({"tasks": cfg.get('tasks', [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/api/memory/stats')
def api_memory_stats():
    from agent.memory import load_memory_from_config
    mem = load_memory_from_config(str(BASE_DIR / 'config.yaml'))
    return jsonify(mem.get_stats())


@config_bp.route('/api/memory/clear', methods=['POST'])
def api_memory_clear():
    from agent.memory import load_memory_from_config
    mem = load_memory_from_config(str(BASE_DIR / 'config.yaml'))
    if not mem.enabled:
        return jsonify({"ok": False, "error": "记忆功能未启用，请先在设置中开启"}), 400
    mem.clear()
    return jsonify({"ok": True})
