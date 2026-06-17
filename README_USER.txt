DataAgent v3.0-beta1 — Windows 内测版

══════════════════════════════════════════════════
  系统要求
══════════════════════════════════════════════════
  • Windows 10 / 11（64 位）
  • Python 3.11（仅 zip 包需要；exe 包自带运行时）
  • 4 GB+ RAM
  • WebView2 Runtime（Windows 11 自带，Windows 10 可能需要安装）
    下载：https://developer.microsoft.com/microsoft-edge/webview2/

══════════════════════════════════════════════════
  方式 A — EXE 包（推荐，无需安装 Python）
══════════════════════════════════════════════════
  1. 解压 DataAgent-v3.0-beta1-exe.zip 到任意目录
  2. 编辑 DataAgent/config.yaml，填写 LLM API Key
  3. 双击 DataAgent.exe 启动

══════════════════════════════════════════════════
  方式 B — ZIP 源码包（需要 Python 3.11）
══════════════════════════════════════════════════
  1. 安装 Python 3.11（https://www.python.org/downloads/）
     勾选 "Add Python to PATH"
  2. 解压 DataAgent-v3.0-beta1.zip 到任意目录
  3. 双击 setup.bat 等待安装完成
  4. 编辑 DataAgent/config.yaml，填写 LLM API Key
  5. 双击 run.bat 启动

══════════════════════════════════════════════════
  配置文件说明
══════════════════════════════════════════════════
  首次启动前必须编辑 config.yaml（config.example.yaml 是模板）：

  llm:
    sql_gen:
      primary: deepseek        # 或 enterprise_internal
      fallback: deepseek
    deepseek:
      url: https://api.deepseek.com/v1
      model: deepseek-chat
      api_key: sk-xxxxxxxx     # ← 替换为你的 API Key

  详细说明见 config.example.yaml 注释。

══════════════════════════════════════════════════
  包含功能（v3.0）
══════════════════════════════════════════════════
  • 数据上传（CSV/Excel/Word/PDF，GB18030/UTF-8 自动识别）
  • 自然语言查询（探索式分析）
  • 固化计算（集中度/净值/收益率/资产结构/信用分布/杠杆率/流动性）
  • 分析技能卡片（就绪状态 + 一键执行）
  • 图表生成（柱状图/饼图/折线图/散点图）
  • 报告生成（Markdown + Word 导出）
  • 合规审计日志
  • 参谈要点 + 合规监控
  • 本地工作目录（批量上传）
  • 置信度标签（✓ 已审计 / ~ 需核实 / ✧ AI生成）

══════════════════════════════════════════════════
  问题反馈
══════════════════════════════════════════════════
  联系：<内部沟通渠道>
