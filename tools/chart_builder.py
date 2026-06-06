"""
tools/chart_builder.py — ECharts 图表选项生成（I-3）

职责：将结构化数据转换为 ECharts option JSON。
支持 pie / bar / line / waterfall 四种图表类型。

设计原则：
  - 返回纯数据 dict（ECharts option），不含 HTML/DOM 操作
  - 每种图表类型有默认配置，通过 options 参数可局部覆盖
  - 数据来源必须是固化计算结果（不直接从 LLM 生成数值）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChartResult:
    ok: bool
    option: dict = field(default_factory=dict)
    title: str = ""
    chart_type: str = ""
    error: str = ""


# ═══════════════════════════════════════════════════════════════
#  公开接口
# ═══════════════════════════════════════════════════════════════

def build_chart(
    chart_type: str,
    data: dict,
    title: str = "",
    options: dict | None = None,
) -> ChartResult:
    """
    根据 chart_type 和 data 生成 ECharts option dict。

    参数:
        chart_type: "pie" | "bar" | "line" | "waterfall"
        data:       图表数据（格式见各 _build_* 函数说明）
        title:      图表标题
        options:    局部覆盖 ECharts option（深合并）

    返回: ChartResult（ok=True 时 option 字段有内容）
    """
    builders = {
        "pie": _build_pie,
        "bar": _build_bar,
        "line": _build_line,
        "waterfall": _build_waterfall,
    }
    builder = builders.get(chart_type)
    if builder is None:
        return ChartResult(
            ok=False,
            error=f"不支持的图表类型：{chart_type}（支持：{', '.join(builders)}）",
        )

    try:
        option = builder(data, title)
        if options:
            option = _deep_merge(option, options)
        return ChartResult(ok=True, option=option, title=title, chart_type=chart_type)
    except (KeyError, ValueError, TypeError) as e:
        return ChartResult(ok=False, error=f"图表数据格式错误：{str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════
#  图表构建器
# ═══════════════════════════════════════════════════════════════

def _build_pie(data: dict, title: str) -> dict:
    """
    饼图。data 格式：
      {"items": [{"name": "AAA", "value": 30.5}, ...]}
    或来自 asset_structure/credit_distribution 计算器的 structure/distribution 字段。
    """
    items = _extract_pie_items(data)
    return {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"orient": "vertical", "left": "left", "top": "middle"},
        "series": [{
            "type": "pie",
            "radius": ["35%", "65%"],
            "center": ["60%", "50%"],
            "data": items,
            "label": {"formatter": "{b}\n{d}%", "fontSize": 11},
            "emphasis": {
                "itemStyle": {
                    "shadowBlur": 10,
                    "shadowOffsetX": 0,
                    "shadowColor": "rgba(0,0,0,0.5)",
                }
            },
        }],
    }


def _build_bar(data: dict, title: str) -> dict:
    """
    柱状图。data 格式：
      {"categories": ["A", "B", ...], "series": [{"name": "集中度", "values": [8.5, 12.1, ...]}]}
    或来自 entity_concentration 计算器的 breaches 字段。
    """
    categories, series = _extract_bar_data(data)
    series_opts = []
    for s in series:
        series_opts.append({
            "type": "bar",
            "name": s["name"],
            "data": s["values"],
            "label": {"show": True, "position": "top", "fontSize": 11},
        })

    return {
        "title": {"text": title, "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 30} if len(series) > 1 else {"show": False},
        "xAxis": {
            "type": "category",
            "data": categories,
            "axisLabel": {"rotate": 30, "fontSize": 11},
        },
        "yAxis": {"type": "value"},
        "series": series_opts,
        "grid": {"bottom": 80},
    }


def _build_line(data: dict, title: str) -> dict:
    """
    折线图。data 格式：
      {"categories": ["2026-01", ...], "series": [{"name": "产品A", "values": [1.05, 1.06, ...]}]}
    适用于净值走势等时序数据。
    """
    categories = data.get("categories", [])
    series_raw = data.get("series", [])
    series_opts = []
    for s in series_raw:
        series_opts.append({
            "type": "line",
            "name": s.get("name", ""),
            "data": s.get("values", []),
            "smooth": True,
            "symbol": "circle",
            "symbolSize": 4,
        })

    return {
        "title": {"text": title, "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 30} if len(series_opts) > 1 else {"show": False},
        "xAxis": {"type": "category", "data": categories, "boundaryGap": False},
        "yAxis": {"type": "value"},
        "series": series_opts,
    }


def _build_waterfall(data: dict, title: str) -> dict:
    """
    瀑布图（用柱状图模拟）。data 格式：
      {"categories": ["期初", "收益", "赎回", "期末"], "values": [100, 20, -15, 105]}
    """
    categories = data.get("categories", [])
    values = data.get("values", [])

    helpers = []
    running = 0
    bar_vals = []
    for v in values:
        helpers.append(running if v >= 0 else running + v)
        bar_vals.append(abs(v))
        running += v

    colors = [
        "#5470c6" if i == 0 or i == len(values) - 1 else
        ("#91cc75" if v >= 0 else "#ee6666")
        for i, v in enumerate(values)
    ]

    return {
        "title": {"text": title, "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "bar",
                "stack": "total",
                "data": helpers,
                "itemStyle": {"opacity": 0},
                "tooltip": {"show": False},
            },
            {
                "type": "bar",
                "stack": "total",
                "data": [
                    {"value": v, "itemStyle": {"color": colors[i]}}
                    for i, v in enumerate(bar_vals)
                ],
                "label": {"show": True, "position": "top", "fontSize": 11},
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════
#  数据提取辅助
# ═══════════════════════════════════════════════════════════════

def _extract_pie_items(data: dict) -> list[dict]:
    """从多种数据格式中提取饼图数据点 [{name, value}, ...]"""
    if "items" in data:
        return [{"name": str(i["name"]), "value": round(float(i["value"]), 2)}
                for i in data["items"]]

    if "structure" in data:
        return [
            {"name": str(r.get("category", r.get("product", "未知"))),
             "value": round(float(r["ratio_pct"]), 2)}
            for r in data["structure"] if r.get("ratio_pct") is not None
        ]

    if "distribution" in data:
        return [
            {"name": str(r.get("rating", "未知")),
             "value": round(float(r["ratio_pct"]), 2)}
            for r in data["distribution"] if r.get("ratio_pct") is not None
        ]

    raise ValueError("pie 图表数据需要包含 items / structure / distribution 字段")


def _extract_bar_data(data: dict) -> tuple[list, list]:
    """从多种数据格式中提取柱状图数据 (categories, series)"""
    if "categories" in data and "series" in data:
        return data["categories"], data["series"]

    if "breaches" in data:
        breaches = data["breaches"]
        cats = [str(b.get("entity_or_bond", "未知")) for b in breaches]
        vals = [round(float(b.get("concentration_pct", 0)), 2) for b in breaches]
        return cats, [{"name": "集中度%", "values": vals}]

    raise ValueError("bar 图表数据需要包含 categories+series 或 breaches 字段")


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 dict，override 优先"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
