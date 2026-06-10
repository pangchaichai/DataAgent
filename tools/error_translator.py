"""
tools/error_translator.py

用户侧错误话术翻译层

将技术异常转换为业务人员可理解的中文提示。
禁止在用户界面显示技术性错误码或堆栈信息。
"""

ERROR_TRANSLATIONS = {
    # 数据加载类
    "no such table":
        "数据表还未加载，请先将对应的 CSV/Excel 文件拖入对话窗口。",
    "no such column":
        "在数据表中找不到所需字段，请确认上传的文件是否为正确类型的数据。",
    "codec can't decode":
        "文件读取遇到编码问题，请确认文件是否损坏，或联系管理员。",
    "UnicodeDecodeError":
        "文件读取遇到编码问题，请确认文件是否损坏，或联系管理员。",
    "FileNotFoundError":
        "找不到指定的文件，请检查文件路径是否正确。",

    # SQL 执行类
    "LIMIT is required":
        "查询范围过大，系统已限制返回行数，请缩小查询条件后重试。",
    "only SELECT is allowed":
        "当前仅支持数据查询操作，不支持修改数据的操作。",
    "referenced table not loaded":
        "查询引用了尚未加载的数据表，请先上传对应数据文件。",
    "read_csv_auto is not allowed":
        "出于安全考虑，不允许直接读取本地文件路径，请通过拖拽方式上传文件。",
    "COPY is not allowed":
        "出于安全考虑，不允许将数据直接导出到本地文件路径。",

    # LLM 调用类
    "connection refused":
        "AI 服务暂时无法连接，请检查网络连接或确认 LLM 服务已启动。可在设置面板中测试连接状态。",
    "timeout":
        "AI 服务响应超时，请稍后重试，或检查网络连接。",
    "api_key":
        "AI 服务认证失败（HTTP 401/403），请检查：1）API Key 是否正确且未过期；2）模型名称是否正确（如 DeepSeek 应为 deepseek-chat）。可在设置面板中点击「测试」确认连接。",
    "llm 服务地址未配置":
        "AI 服务地址未配置，请在设置面板中配置 LLM 提供方的服务地址。",
    "内网 llm 不可用且不允许外发":
        "内网 AI 服务不可用且未启用外部兜底，请检查内网 LLM 服务状态，或在设置中启用外部 LLM 作为备选。",

    # 数据校验类
    "product_not_in_data":
        "在数据表中找不到该产品名称，请确认产品名称是否正确，或检查是否已上传对应数据文件。",
    "data_date_expired":
        "当前加载的数据不是今日最新数据，合规监控计算已停止。请上传今日最新数据后重试。",
    "join_key_mismatch":
        "以下主体在两张表中无法对齐，可能导致数据遗漏，请确认后继续：\n{details}",
}


def translate(error: Exception | str, details: str = "") -> str:
    """
    将技术异常转换为用户可理解的提示文字。
    unknown 错误给出通用提示，不暴露技术细节。
    """
    error_str = str(error).lower() if isinstance(error, Exception) else error.lower()
    for key, message in ERROR_TRANSLATIONS.items():
        if key.lower() in error_str:
            return message.format(details=details) if "{details}" in message else message
    brief = str(error)[:100] if error else ""
    if brief:
        return f"操作遇到异常：{brief}。如需进一步帮助，请输入「继续」或截图反馈。"
    return "操作遇到异常，请输入「继续」重试，或截图反馈。"
