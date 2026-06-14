"""
tools/compliance_audit.py — 合规级审计日志

职责：
  记录所有合规场景的计算过程，保证事后可复现：
  - 用了哪个数据文件的哪个版本（日期+指纹）
  - 用的是哪段 SQL 或哪个版本的固化公式
  - 阈值是多少
  - 谁确认的

所有日志写入 data/compliance_audit/ 目录的 JSONL 文件，追加写入不覆盖。
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class AuditEvent:
    event_type: str           # 'monitoring' / 'report' / 'query'
    skill_name: str
    data_files: list[dict]    # [{name, date, fingerprint(md5)}]
    sql_or_formula: str       # 实际执行的 SQL 或固化公式版本号
    thresholds: dict          # 使用的阈值参数
    result_summary: dict      # 结果摘要（不含完整数据行）
    confirmed_by: str         # 用户名
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    prev_hash: str = ""       # 上一条记录的 SHA256（hash chain，I-5b）


@dataclass
class AuditResult:
    ok: bool
    event_id: str = ""
    error: str = ""


# ═══════════════════════════════════════════════════════════════
#  日志目录
# ═══════════════════════════════════════════════════════════════

def _audit_dir() -> Path:
    base = Path(__file__).resolve().parent.parent / 'data' / 'compliance_audit'
    base.mkdir(parents=True, exist_ok=True)
    return base


def _log_file() -> Path:
    """按日期分文件，避免单文件过大"""
    date_str = datetime.now().strftime('%Y%m%d')
    return _audit_dir() / f'audit_{date_str}.jsonl'


# ═══════════════════════════════════════════════════════════════
#  MD5 指纹
# ═══════════════════════════════════════════════════════════════

def _file_fingerprint(file_path: str) -> str:
    """计算文件的 MD5 指纹（仅取前 1MB 避免大文件耗时）"""
    if not os.path.isfile(file_path):
        return 'MISSING'
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            h.update(f.read(1024 * 1024))
        return h.hexdigest()
    except Exception:
        return 'ERROR'


# ─── Hash chain ──────────────────────────────────────────────

_CHAIN_SEED = "dataagent-audit-chain-seed-v1"


def _get_last_hash() -> str:
    """
    返回今日审计日志最后一行的 SHA256（hash chain 前置哈希）。
    无记录时返回种子哈希。
    """
    log_path = _log_file()
    if not log_path.exists():
        return hashlib.sha256(_CHAIN_SEED.encode()).hexdigest()
    last_line = b""
    try:
        with open(log_path, 'rb') as f:
            for line in f:
                if line.strip():
                    last_line = line.strip()
    except Exception:
        pass
    if not last_line:
        return hashlib.sha256(_CHAIN_SEED.encode()).hexdigest()
    return hashlib.sha256(last_line).hexdigest()


def verify_chain(date_str: str = "") -> tuple[bool, str]:
    """
    验证指定日期审计日志的 hash chain 完整性。
    返回 (ok, message)。
    """
    events = read_audit_log(date_str)
    if not events:
        return True, "无日志记录"

    seed_hash = hashlib.sha256(_CHAIN_SEED.encode()).hexdigest()
    prev = seed_hash

    log_lines = []
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    log_path = _audit_dir() / f'audit_{date_str}.jsonl'
    if log_path.exists():
        with open(log_path, 'rb') as f:
            log_lines = [ln.strip() for ln in f if ln.strip()]

    for i, (event, raw) in enumerate(zip(events, log_lines, strict=False)):
        expected_prev = prev
        actual_prev = event.get('prev_hash', '')
        if actual_prev != expected_prev:
            return False, f"第 {i+1} 条记录 prev_hash 不匹配（链断裂）"
        prev = hashlib.sha256(raw).hexdigest()

    return True, f"链完整，共 {len(events)} 条记录"


# ═══════════════════════════════════════════════════════════════
#  核心接口
# ═══════════════════════════════════════════════════════════════

def log_compliance_event(
    event_type: str,
    skill_name: str,
    data_files: list[dict],        # [{name, path, date}]
    sql_or_formula: str,
    thresholds: dict,
    result_summary: dict,
    confirmed_by: str = "",
) -> AuditResult:
    """
    记录合规事件审计日志。

    参数:
      event_type:      'monitoring' / 'report' / 'query'
      skill_name:      触发的 Skill 名称
      data_files:      使用的数据文件列表，每项含 name, path, date
      sql_or_formula:  实际执行的 SQL 或固化公式版本号
      thresholds:      阈值参数（如 {'threshold_entity': 10.0}）
      result_summary:  结果摘要（如 {'breach_count': 3}），严禁包含完整数据行
      confirmed_by:    确认人姓名

    数据安全：
      - result_summary 只记录统计摘要，不记录具体数值
      - 完整数据行不写入审计日志（防止审计日志本身成为数据泄露源）
    """
    # 验证：禁止在 result_summary 中包含完整数据行
    for key in result_summary:
        if isinstance(result_summary[key], list) and len(result_summary[key]) > 10:
            return AuditResult(ok=False, error=f"result_summary 禁止包含完整数据行: {key}")

    # 计算每个数据文件的 MD5 指纹
    files_with_fingerprint = []
    for df in data_files:
        fp = _file_fingerprint(df.get('path', ''))
        files_with_fingerprint.append({
            'name': df.get('name', ''),
            'date': df.get('date', ''),
            'fingerprint': fp,
        })

    # ── Hash chain: prev_hash = SHA256 of last line in today's log ──
    prev_hash = _get_last_hash()

    event = AuditEvent(
        event_type=event_type,
        skill_name=skill_name,
        data_files=files_with_fingerprint,
        sql_or_formula=sql_or_formula,
        thresholds=thresholds,
        result_summary=result_summary,
        confirmed_by=confirmed_by,
        prev_hash=prev_hash,
    )

    try:
        log_path = _log_file()
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + '\n')
        return AuditResult(ok=True, event_id=event.timestamp)
    except Exception as e:
        return AuditResult(ok=False, error=str(e))


def read_audit_log(date_str: str = "") -> list[dict]:
    """
    读取指定日期的审计日志。

    参数:
      date_str: YYYYMMDD 格式，空字符串表示今天
    """
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    log_path = _audit_dir() / f'audit_{date_str}.jsonl'
    if not log_path.exists():
        return []
    events = []
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events
