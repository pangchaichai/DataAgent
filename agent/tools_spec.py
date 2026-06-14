"""
agent/tools_spec.py — 向后兼容的转发层（thin re-export）

原有内容已拆分为：
  agent/tool_defs.py     — TOOL_DEFINITIONS / ToolResult / ToolContext
  agent/tool_dispatch.py — dispatch_tool / _tool_* 实现 / 参数校验 / 超时保护

本文件保留所有公开符号的 re-export，确保所有现有导入无需修改：
  from agent.tools_spec import dispatch_tool, TOOL_DEFINITIONS, ToolContext
"""

from agent.tool_defs import TOOL_DEFINITIONS, ToolContext, ToolResult  # noqa: F401
from agent.tool_dispatch import (  # noqa: F401
    _get_tool_schema,
    _tool_ask_user,
    _tool_confirm_dict,
    _tool_export_data,
    _tool_generate_report,
    _tool_list_tables,
    _tool_profile_table,
    _tool_propose_dict_entry,
    _tool_read_document,
    _tool_render_chart,
    _tool_request_confirmation,
    _tool_run_calculator,
    _tool_run_sql,
    _tool_web_search,
    _validate_tool_args,
    _with_timeout,
    dispatch_tool,
)
