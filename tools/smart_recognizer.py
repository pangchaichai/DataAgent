"""
tools/smart_recognizer.py — 智能数据识别协调器

职责：
  1. smart_detect_table_type：LLM 增强的表类型识别（程序化检测失败时调用）
  2. smart_field_mapping：LLM 推断未知字段语义映射
  3. generate_draft_dictionary：为未知表类型生成完整字典草稿 YAML

设计原则：
  - 程序化优先：仅在确定性检测失败/低置信时才调 LLM
  - 数据安全：LLM 仅接收列名 + 文件名 + 脱敏样本，不发实际数据值
  - 超时降级：LLM 调用 10s 超时，失败静默回退
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class SmartDetectionResult:
    """智能表类型识别结果"""
    table_type: str
    confidence: float
    reason: str
    source: str  # 'programmatic' | 'llm' | 'fallback'
    llm_suggestion: str = ""


@dataclass
class FieldMappingProposal:
    """单个字段的映射推断提案"""
    column_name: str
    proposed_semantic: str
    confidence: float
    reason: str


@dataclass
class DraftDictionaryResult:
    """字典草稿生成结果"""
    ok: bool
    table_type: str
    yaml_content: str = ""
    draft_path: str = ""
    field_count: int = 0
    error: str = ""


# ═══════════════════════════════════════════════════════════════
#  候选类型描述（供 LLM 参考）
# ═══════════════════════════════════════════════════════════════

_TYPE_DESCRIPTIONS = {
    "holding": "持仓数据（产品持仓明细，含市值、资产代码、穿透后市值等）",
    "nav": "净值数据（产品净值、累计净值、万份收益、七日年化等）",
    "rating_entity": "主体评级数据（发行人/主体信用评级，含主体名称、评级等级等）",
    "rating_bond": "债券评级数据（债券/债项评级，含债券代码、ISIN、评级等级等）",
    "monitoring": "监控值数据（风控指标监控，含监控指标名称、阈值、当前值等）",
    "weekly_report": "周报数据源（周报用数据汇总，含统计日期、组合代码、产品标签等）",
    "holding_detail": "底层资产持仓明细（穿透后的底层资产持仓，含债券信息等）",
    "valuation": "估值表数据（产品估值明细，含估值日期、科目代码、市值等）",
    "subscription": "申赎数据（产品申购赎回记录，含确认金额、确认份额等）",
    "asset_position": "资产头寸数据（实时资产头寸查询，含资产类型、持有数量等）",
    "cashflow_gap": "现金流缺口数据（现金流缺口分析，含期限区间、到期金额等）",
    "bond_pledge": "债券质押数据（债券质押查询，含质押券代码、质押金额等）",
    "account_flow": "账户流水数据（资金账户流水，含交易日期、收支金额等）",
    "repo_trade": "质押式回购数据（回购交易查询，含回购利率、到期日等）",
    "fund_position": "组合资金头寸（资金账户头寸，含可用余额、冻结金额等）",
}


# ═══════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════

def _build_type_candidates_text() -> str:
    """构建候选类型列表文本（供 LLM prompt 使用）。"""
    lines = []
    for type_name, desc in _TYPE_DESCRIPTIONS.items():
        lines.append(f"  - {type_name}: {desc}")
    return "\n".join(lines)


def _sanitize_preview_values(df_preview, max_rows: int = 3) -> list[dict]:
    """脱敏预览行：仅保留结构信息，隐藏具体数据值。"""
    from tools.profiler import _sanitize_samples

    sanitized_rows = []
    for _, row in df_preview.head(max_rows).iterrows():
        sanitized_row = {}
        for col in df_preview.columns:
            val = str(row[col]) if row[col] is not None else ""
            sanitized = _sanitize_samples([val], col)
            sanitized_row[col] = sanitized[0] if sanitized else ""
        sanitized_rows.append(sanitized_row)
    return sanitized_rows


# ═══════════════════════════════════════════════════════════════
#  迭代 1：智能表类型识别
# ═══════════════════════════════════════════════════════════════

def smart_detect_table_type(
    df_preview,
    filename: str,
    programmatic_result: str,
    programmatic_scores: dict | None = None,
) -> SmartDetectionResult:
    """
    LLM 增强的表类型识别。

    触发条件（由调用方判断）：
      - programmatic_result == 'unknown'（关键词匹配得分为0）
      - 或最高得分 <= 1（低置信）

    流程：
      1. 构建脱敏上下文（列名 + 文件名 + 脱敏样本）
      2. LLM function-calling 返回 {type, confidence, reason}
      3. 超时/失败 → 静默回退 programmatic_result

    LLM 仅接收元信息，不接收实际数据值。
    """
    if programmatic_result != 'unknown' and (
        programmatic_scores and max(programmatic_scores.values(), default=0) > 1
    ):
        return SmartDetectionResult(
            table_type=programmatic_result,
            confidence=1.0,
            reason="程序化检测高置信",
            source="programmatic",
        )

    columns = list(df_preview.columns)
    sanitized_rows = _sanitize_preview_values(df_preview)

    type_candidates_text = _build_type_candidates_text()
    prompt_content = (
        f"文件名：{filename}\n"
        f"列名列表：{json.dumps(columns, ensure_ascii=False)}\n"
        f"脱敏样本行：{json.dumps(sanitized_rows, ensure_ascii=False)}\n\n"
        f"已知的表类型及描述：\n{type_candidates_text}\n\n"
        f"程序化检测结果：{programmatic_result}"
        + (f"（得分：{json.dumps(programmatic_scores, ensure_ascii=False)}）"
           if programmatic_scores else "")
    )

    tools_def = [{
        "type": "function",
        "function": {
            "name": "classify_table_type",
            "description": "根据列名和文件名判断数据表类型",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_type": {
                        "type": "string",
                        "description": "判断的表类型，必须是候选列表中的一个，如果都不匹配则为 unknown",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "置信度 0.0-1.0",
                    },
                    "reason": {
                        "type": "string",
                        "description": "判断依据（简要说明）",
                    },
                },
                "required": ["table_type", "confidence", "reason"],
            },
        },
    }]

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个数据分类专家。根据数据表的列名、文件名和脱敏样本，"
                "判断该数据表属于哪种业务类型。"
                "只能从给定的候选类型中选择，如果无法确定则返回 unknown。"
                "注意：样本值已脱敏，仅用于判断数据结构，不要尝试还原具体数据。"
            ),
        },
        {"role": "user", "content": prompt_content},
    ]

    try:
        from agent.llm_client import LLMClient
        client = LLMClient()
        result = client.chat(messages, tools=tools_def, timeout=10, max_tokens=500)

        if not result.success:
            logger.info("[smart_recognizer] LLM 调用失败，回退程序化结果: %s", result.error)
            return SmartDetectionResult(
                table_type=programmatic_result,
                confidence=0.0,
                reason=f"LLM 不可用（{result.error[:80]}），使用程序化结果",
                source="fallback",
            )

        if result.tool_calls:
            tc = result.tool_calls[0]
            args = tc.get("arguments", {})
            detected_type = args.get("table_type", "unknown")
            confidence = float(args.get("confidence", 0.0))
            reason = args.get("reason", "")

            valid_types = set(_TYPE_DESCRIPTIONS.keys()) | {"unknown"}
            if detected_type not in valid_types:
                detected_type = "unknown"

            return SmartDetectionResult(
                table_type=detected_type,
                confidence=confidence,
                reason=reason,
                source="llm",
                llm_suggestion=f"{detected_type}（{reason}）",
            )

        if result.text:
            return SmartDetectionResult(
                table_type=programmatic_result,
                confidence=0.3,
                reason=f"LLM 未返回结构化结果，使用程序化结果。LLM 文本：{result.text[:100]}",
                source="fallback",
            )

    except Exception as e:
        logger.info("[smart_recognizer] LLM 调用异常，静默回退: %s", e)

    return SmartDetectionResult(
        table_type=programmatic_result,
        confidence=0.0,
        reason="LLM 调用异常，使用程序化结果",
        source="fallback",
    )


# ═══════════════════════════════════════════════════════════════
#  迭代 2：智能字段映射推断
# ═══════════════════════════════════════════════════════════════

def smart_field_mapping(
    column_names: list[str],
    sample_values: dict[str, list[str]],
    table_type: str,
    existing_dict: dict | None = None,
) -> list[FieldMappingProposal]:
    """
    批量推断未映射字段的语义。

    参数：
      column_names:   需要推断的列名列表
      sample_values:  {列名: [脱敏样本值]}（已脱敏）
      table_type:     当前表类型
      existing_dict:  当前表的字典定义（如有），供 LLM 参考已映射字段

    返回 FieldMappingProposal 列表，每个包含推断的语义名和置信度。
    """
    if not column_names:
        return []

    existing_fields = []
    if existing_dict:
        for f in existing_dict.get('fields', []):
            existing_fields.append({
                "semantic": f['semantic'],
                "physical_candidates": f.get('physical_candidates', []),
            })

    columns_info = []
    for col in column_names[:30]:
        info = {"column_name": col}
        if col in sample_values:
            info["sanitized_samples"] = sample_values[col][:3]
        columns_info.append(info)

    type_desc = _TYPE_DESCRIPTIONS.get(table_type, "未知类型")

    prompt_content = (
        f"表类型：{table_type}（{type_desc}）\n"
        f"已有字段映射：{json.dumps(existing_fields, ensure_ascii=False)}\n\n"
        f"需要推断语义的列：\n{json.dumps(columns_info, ensure_ascii=False)}\n\n"
        f"请为每个列推断其业务语义名称。"
    )

    tools_def = [{
        "type": "function",
        "function": {
            "name": "propose_field_mappings",
            "description": "为未映射的数据列推断业务语义名称",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposals": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column_name": {"type": "string"},
                                "proposed_semantic": {
                                    "type": "string",
                                    "description": "推断的业务语义名称",
                                },
                                "confidence": {
                                    "type": "number",
                                    "description": "置信度 0.0-1.0",
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["column_name", "proposed_semantic", "confidence"],
                        },
                    },
                },
                "required": ["proposals"],
            },
        },
    }]

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个金融数据字段分析专家。根据列名、脱敏样本和表类型，"
                "推断每个数据列的业务语义名称。"
                "语义名称应简洁且符合中文金融业务惯例。"
                "注意：样本值已脱敏，仅用于辅助判断字段类型。"
            ),
        },
        {"role": "user", "content": prompt_content},
    ]

    try:
        from agent.llm_client import LLMClient
        client = LLMClient()
        result = client.chat(messages, tools=tools_def, timeout=15, max_tokens=1500)

        if not result.success or not result.tool_calls:
            logger.info("[smart_recognizer] 字段映射 LLM 调用失败: %s", result.error)
            return []

        tc = result.tool_calls[0]
        args = tc.get("arguments", {})
        proposals_raw = args.get("proposals", [])

        proposals = []
        valid_columns = set(column_names)
        for p in proposals_raw:
            col = p.get("column_name", "")
            if col not in valid_columns:
                continue
            proposals.append(FieldMappingProposal(
                column_name=col,
                proposed_semantic=p.get("proposed_semantic", col),
                confidence=float(p.get("confidence", 0.0)),
                reason=p.get("reason", ""),
            ))
        return proposals

    except Exception as e:
        logger.info("[smart_recognizer] 字段映射异常: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════
#  迭代 3：字典草稿自动生成
# ═══════════════════════════════════════════════════════════════

def generate_draft_dictionary(
    column_names: list[str],
    sample_values: dict[str, list[str]],
    table_type: str,
    filename: str = "",
) -> DraftDictionaryResult:
    """
    为未知/新增表类型生成完整的字典草稿 YAML。

    流程：
      1. 调用 smart_field_mapping 推断字段语义
      2. 组装为标准字典 YAML 格式
      3. 写入 data_dictionary/drafts/{table_type}_dict_draft.yaml

    生成的草稿需人工确认后才能合并到正式字典。
    """
    proposals = smart_field_mapping(
        column_names, sample_values, table_type,
    )

    fields = []
    for col in column_names:
        matching = [p for p in proposals if p.column_name == col]
        if matching:
            p = matching[0]
            field_entry = {
                "semantic": p.proposed_semantic,
                "physical_candidates": [col],
                "required": p.confidence >= 0.8,
            }
            if p.confidence < 0.5:
                field_entry["_draft_note"] = f"低置信（{p.confidence:.1f}），请人工确认"
        else:
            field_entry = {
                "semantic": col,
                "physical_candidates": [col],
                "required": False,
                "_draft_note": "未经 LLM 推断，直接使用列名作为语义名",
            }
        fields.append(field_entry)

    dict_data = {
        "table_type": table_type,
        "description": _TYPE_DESCRIPTIONS.get(table_type, f"由智能识别自动生成（{filename}）"),
        "_draft": True,
        "_source_file": filename,
        "fields": fields,
    }

    yaml_content = yaml.dump(
        dict_data, allow_unicode=True, default_flow_style=False, sort_keys=False,
    )

    drafts_dir = Path(__file__).resolve().parent.parent / "data_dictionary" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / f"{table_type}_dict_draft.yaml"
    try:
        draft_path.write_text(yaml_content, encoding='utf-8')
    except Exception as e:
        return DraftDictionaryResult(
            ok=False, table_type=table_type,
            error=f"写入草稿失败：{e}",
        )

    return DraftDictionaryResult(
        ok=True,
        table_type=table_type,
        yaml_content=yaml_content,
        draft_path=str(draft_path),
        field_count=len(fields),
    )


# ═══════════════════════════════════════════════════════════════
#  公开协调接口
# ═══════════════════════════════════════════════════════════════

def enhanced_detect_table_type(
    df_preview,
    filename: str,
) -> SmartDetectionResult:
    """
    增强版表类型检测：先程序化检测，低置信时自动调 LLM。

    供 api/data.py Stage 1 上传预览调用。
    """
    from tools.data_loader import _detect_with_scores

    programmatic_result, scores = _detect_with_scores(df_preview, filename)
    best_score = max(scores.values(), default=0)

    if best_score > 1:
        return SmartDetectionResult(
            table_type=programmatic_result,
            confidence=min(best_score / 5.0, 1.0),
            reason=f"程序化检测（得分 {best_score}）",
            source="programmatic",
        )

    return smart_detect_table_type(
        df_preview, filename, programmatic_result, scores,
    )


def on_data_load_check_unmatched(
    table_name: str,
    table_type: str,
    unmatched_cols: list[str],
    total_cols: int,
    df_preview=None,
    filename: str = "",
) -> DraftDictionaryResult | None:
    """
    数据加载后 hook：未匹配列超过 50% 时自动生成字典草稿。

    由 agent/hooks.py 的 on_data_load 事件触发。
    返回 DraftDictionaryResult 或 None（不需要生成）。
    """
    if total_cols == 0 or len(unmatched_cols) / total_cols < 0.5:
        return None

    if table_type == "unknown":
        return None

    from tools.profiler import _sanitize_samples
    sample_values: dict[str, list[str]] = {}
    if df_preview is not None:
        for col in unmatched_cols:
            if col in df_preview.columns:
                vals = [str(v) for v in df_preview[col].head(3) if v is not None]
                sample_values[col] = _sanitize_samples(vals, col)

    return generate_draft_dictionary(
        unmatched_cols, sample_values, table_type, filename,
    )
