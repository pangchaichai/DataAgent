"""
api/skill_api.py — Skills 注册与 Skill Builder 路由
"""
from flask import Blueprint, jsonify, request

from session_store import BASE_DIR

skill_bp = Blueprint('skill', __name__)


@skill_bp.route('/api/skills')
def api_skills():
    from agent.skill_loader import SkillLoader
    loader = SkillLoader(local_dir=str(BASE_DIR / 'skills'))
    registry = loader.load_registry()
    skills = [
        {
            "name": s.name,
            "description": s.description.split('\n')[0][:80],
            "calc_type": s.calc_type,
        }
        for s in registry
    ]
    return jsonify({"skills": skills})


@skill_bp.route('/api/skill-builder/drafts')
def api_skill_drafts():
    from tools.skill_builder import list_drafts
    return jsonify({"drafts": list_drafts()})


@skill_bp.route('/api/skill-builder/generate', methods=['POST'])
def api_skill_generate():
    data = request.get_json(force=True) if request.is_json else {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({"ok": False, "error": "请描述你想创建的 Skill 功能"}), 400

    from agent.llm_client import LLMClient
    from tools.skill_builder import (
        build_skill_generation_prompt,
        generate_skill_md,
        parse_llm_skill_response,
        save_draft,
    )

    try:
        llm = LLMClient(str(BASE_DIR / 'config.yaml'))
        from agent.context import build_schema_context
        data_context = build_schema_context()
        prompt = build_skill_generation_prompt(description, data_context=data_context)
        result = llm.chat(
            [{"role": "user", "content": prompt}],
            tools=None,
        )
        if not result.success or not result.text:
            return jsonify({"ok": False, "error": "AI 生成失败，请重试"}), 500

        draft = parse_llm_skill_response(result.text)
        if not draft:
            return jsonify({"ok": False, "error": "AI 返回格式异常，请重新描述"}), 500

        content = generate_skill_md(draft)
        save_draft(draft.name, content)

        return jsonify({
            "ok": True,
            "name": draft.name,
            "content": content,
            "draft": {
                "name": draft.name,
                "description": draft.description,
                "trigger_words": draft.trigger_words,
                "calc_type": draft.calc_type,
            },
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"生成异常：{str(e)[:200]}"}), 500


@skill_bp.route('/api/skill-builder/import', methods=['POST'])
def api_skill_import():
    data = request.get_json(force=True) if request.is_json else {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({"ok": False, "error": "请提供需求文档内容"}), 400

    from agent.context import build_schema_context
    from tools.skill_builder import import_from_requirement_doc

    data_context = build_schema_context()
    result = import_from_requirement_doc(content, data_context=data_context)
    status = 200 if result.get('ok') else 500
    return jsonify(result), status


@skill_bp.route('/api/skill-builder/validate', methods=['POST'])
def api_skill_validate():
    data = request.get_json(force=True) if request.is_json else {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({"ok": False, "error": "内容为空"}), 400

    from tools.skill_builder import validate_skill_md
    result = validate_skill_md(content, str(BASE_DIR / 'skills'))
    return jsonify(result.to_dict())


@skill_bp.route('/api/skill-builder/save-draft', methods=['POST'])
def api_skill_save_draft():
    data = request.get_json(force=True) if request.is_json else {}
    name = (data.get('name') or '').strip()
    content = (data.get('content') or '').strip()
    if not name or not content:
        return jsonify({"ok": False, "error": "名称或内容为空"}), 400

    from tools.skill_builder import save_draft
    return jsonify(save_draft(name, content))


@skill_bp.route('/api/skill-builder/draft/<name>')
def api_skill_load_draft(name):
    from tools.skill_builder import load_draft
    content = load_draft(name)
    if content is None:
        return jsonify({"error": "草稿不存在"}), 404
    return jsonify({"ok": True, "name": name, "content": content})


@skill_bp.route('/api/skill-builder/draft/<name>', methods=['DELETE'])
def api_skill_delete_draft(name):
    from tools.skill_builder import delete_draft
    if not delete_draft(name):
        return jsonify({"ok": False, "error": "草稿不存在"}), 404
    return jsonify({"ok": True})


@skill_bp.route('/api/skill-builder/publish', methods=['POST'])
def api_skill_publish():
    data = request.get_json(force=True) if request.is_json else {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({"ok": False, "error": "内容为空"}), 400

    from tools.skill_builder import publish_skill
    result = publish_skill(content, str(BASE_DIR / 'skills'))
    status = 200 if result['ok'] else 400
    return jsonify(result), status
