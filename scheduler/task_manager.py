# scheduler/task_manager.py
# 定时任务调度器
# 使用 schedule 库实现，轻量无外部依赖
# 业务逻辑全部由 skills/ 中的 SKILL.md 定义，本模块只负责触发

"""
定时任务调度器

职责：
  1. 读取 tasks/task_config.yaml
  2. 按配置注册定时任务
  3. 在后台线程中持续运行调度循环
  4. 触发时调用对应 Skill 执行分析
  5. 将结果通过 notify.mode 推送给用户

设计原则：
  - 本模块永远不包含业务逻辑（不写SQL、不写计算规则）
  - 业务逻辑全部在 skills/xxx/SKILL.md 中定义
  - 新增定时任务 = 在 task_config.yaml 添加配置项，不改代码
"""

import schedule
import threading
import time
import yaml
from pathlib import Path
from datetime import datetime


class TaskManager:
    def __init__(self, task_config_path: str, agent_loop_fn, notify_fn):
        """
        task_config_path: tasks/task_config.yaml 路径
        agent_loop_fn: 调用 Agent 执行分析的函数（传入指令字符串）
        notify_fn: 推送通知的函数（mode, message）
        """
        self.config_path = task_config_path
        self.agent_loop_fn = agent_loop_fn
        self.notify_fn = notify_fn
        self.tasks = []
        self._running = False

    def load_and_register(self):
        """
        读取 task_config.yaml，注册所有定时任务。
        可在运行时重新调用以热更新任务配置。
        """
        schedule.clear()  # 清除旧任务
        with open(self.config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)

        for task in config.get('tasks', []):
            self._register_task(task)

    def _register_task(self, task: dict):
        """根据 schedule 字段注册对应的调度规则"""
        sched = task['schedule']
        job_fn = lambda t=task: self._execute_task(t)

        if sched.startswith('daily_'):
            time_str = sched.replace('daily_', '')        # "08:30"
            schedule.every().day.at(time_str).do(job_fn)

        elif sched.startswith('weekly_'):
            parts = sched.replace('weekly_', '').split('_')
            weekday, time_str = parts[0], parts[1]        # "friday", "16:00"
            getattr(schedule.every(), weekday).at(time_str).do(job_fn)

        elif sched.startswith('monthly_'):
            # monthly_01_09:00 → 每月1日09:00
            # 使用 daily 模拟，执行时检查日期
            parts = sched.replace('monthly_', '').split('_')
            day, time_str = int(parts[0]), parts[1]
            def monthly_job(d=day, fn=job_fn):
                if datetime.now().day == d:
                    fn()
            schedule.every().day.at(time_str).do(monthly_job)

    def _execute_task(self, task: dict):
        """
        执行一个定时任务：
        1. 构造自然语言指令（业务人员可读懂的指令）
        2. 调用 Agent Loop 执行
        3. 将结果通过配置的 notify.mode 推送
        """
        # 构造执行指令（模拟用户输入）
        skill_name = task['skill']
        params = task.get('params', {})
        instruction = self._build_instruction(skill_name, params)

        try:
            result = self.agent_loop_fn(instruction, task_mode=True)
            # 格式化通知消息
            message = task['notify']['message_template'].format(
                **result.summary, output_path=result.output_path or ''
            )
            self.notify_fn(task['notify']['mode'], message)
        except Exception as e:
            self.notify_fn('chat', f"⚠️ 定时任务「{task['name']}」执行失败：{str(e)}")

    def _build_instruction(self, skill_name: str, params: dict) -> str:
        """将 task_config 中的参数转换为 Agent 可理解的自然语言指令"""
        instructions = {
            'concentration_monitor': (
                f"执行{params.get('monitor_type', '集中度')}超标监控，"
                f"找出超过{params.get('threshold_value', 10)}%的理财产品，"
                f"按产品和投资经理汇总并生成提示清单"
            ),
            'dept_weekly_report': "生成本周投资部门周报",
            'monthly_bond_summary': "生成本月全公司债券投资情况简报",
        }
        return instructions.get(skill_name, f"执行技能：{skill_name}")

    def on_startup(self):
        """
        启动时调用，检测并提示补跑错过的任务。
        同时校验数据时效。
        """
        print("[TaskManager] 启动检测...")

        # 1. 数据时效校验
        freshness_ok = self._validate_data_freshness(['holding'])
        if not freshness_ok:
            if self.notify_fn:
                self.notify_fn('chat',
                    "⚠️ 当前持仓数据不是今日最新，定时监控任务将暂停。"
                    "请上传今日数据文件后系统将自动恢复监控。")
            return

        # 2. 补跑检测
        missed = self._detect_missed_tasks()
        if missed and self.notify_fn:
            task_names = "、".join([t['name'] for t in missed])
            self.notify_fn('chat',
                f"⚠️ 以下定时任务在软件未运行时错过了：{task_names}\n"
                f"是否立即执行？回复「执行」来补跑，或「跳过」忽略。")

    def _validate_data_freshness(self, required_types: list[str]) -> bool:
        """
        执行定时任务前强制校验所需数据文件的日期是否为今日。

        校验逻辑：
          - 检查已加载的 holding 表的 date_tag 是否为今天
          - 允许 data_max_age_days 天内的滞后（config.yaml 配置）
          - 过期则推送告警，不执行计算（防止假合规）
        """
        from tools.data_loader import get_loaded_tables
        from datetime import datetime, timedelta

        tables = get_loaded_tables()
        today = datetime.now().strftime('%Y%m%d')

        try:
            import yaml
            with open('config.yaml', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            max_age = cfg.get('calculation_config', {}).get('concentration', {}).get('data_max_age_days', 1)
        except Exception:
            max_age = 1

        for table_type in required_types:
            matching = [t for t in tables if t.get('type') == table_type]
            if not matching:
                if self.notify_fn:
                    self.notify_fn('chat', f"⚠️ 未找到 {table_type} 类型的数据表，无法执行监控。")
                return False

            for t in matching:
                date_tag = t.get('date_tag', '')
                if not date_tag:
                    continue  # 无日期标记，跳过校验
                try:
                    data_date = datetime.strptime(date_tag, '%Y%m%d')
                    allowed = datetime.now() - timedelta(days=max_age)
                    if data_date < allowed:
                        if self.notify_fn:
                            from tools.notify import notify_data_expired
                            notify_data_expired(table_type, today, date_tag)
                        return False
                except ValueError:
                    continue

        return True

    def _detect_missed_tasks(self) -> list:
        """
        检测自上次运行以来错过的定时任务。

        通过比对当前时间与各任务的计划执行时间：
          - 如果任务应在今天更早时间执行但尚未执行 → 标记为错过
          - 记录上次执行时间到 data/sessions/last_run.json

        返回: 错过的任务列表 [{name, scheduled_time, skill}, ...]
        """
        import json
        from datetime import datetime
        from pathlib import Path

        now = datetime.now()
        today_str = now.strftime('%Y%m%d')

        # 读取上次运行记录
        run_log_path = Path('data/sessions/last_run.json')
        last_runs = {}
        if run_log_path.exists():
            try:
                with open(run_log_path, encoding='utf-8') as f:
                    last_runs = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        missed = []
        for task in self.tasks:
            task_name = task['name']
            sched = task.get('schedule', '')
            last_run = last_runs.get(task_name, '')

            # 解析调度时间
            target_time = None
            if sched.startswith('daily_'):
                time_str = sched.replace('daily_', '')
                target_time = datetime.strptime(f'{today_str}_{time_str}', '%Y%m%d_%H:%M')
            elif sched.startswith('weekly_'):
                parts = sched.replace('weekly_', '').split('_')
                weekday_name = parts[0]
                time_str = parts[1]
                weekday_map = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                              'friday': 4, 'saturday': 5, 'sunday': 6}
                target_weekday = weekday_map.get(weekday_name.lower())
                if target_weekday is not None and now.weekday() == target_weekday:
                    target_time = datetime.strptime(f'{today_str}_{time_str}', '%Y%m%d_%H:%M')

            if target_time and target_time < now:
                # 检查今天是否已执行
                if last_run != today_str:
                    missed.append({
                        'name': task_name,
                        'scheduled_time': target_time.strftime('%H:%M'),
                        'skill': task.get('skill', ''),
                    })

        # 记录本次检测
        for task in self.tasks:
            last_runs[task['name']] = today_str
        run_log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(run_log_path, 'w', encoding='utf-8') as f:
                json.dump(last_runs, f, ensure_ascii=False)
        except IOError:
            pass

        return missed

    def start_background(self):
        """在后台线程中启动调度循环，不阻塞主线程"""
        self._running = True
        def run():
            while self._running:
                schedule.run_pending()
                time.sleep(30)  # 每30秒检查一次是否有任务需要执行
        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def stop(self):
        self._running = False
        schedule.clear()
