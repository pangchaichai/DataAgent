"""
tools/vendor_api.py — 金融资讯 API 统一适配器

支持供应商：
  - Choice (EmQuantAPI) — 东方财富，P2 优先实现
  - iFind (iFinDPy) — 同花顺，P2 优先实现
  - Wind (WindPy) — 万得，P3 预留接口

约束：
  - Choice/iFind/Wind 均为 Windows-only + 需付费终端授权
  - 未安装对应 Python 包时优雅降级（可用性检测 + UI 灰显）
  - 开发阶段（Linux）做 Mock 测试，Windows UAT 阶段实测
  - 数据获取后通过 load_dataframe() 统一入口进入 DuckDB
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from tools.remote_db import RemoteQueryResult, _decode_password

_CONFIG_PATH = Path(__file__).parent.parent / 'config.yaml'


@dataclass
class VendorStatus:
    name: str
    available: bool
    connected: bool = False
    reason: str = ''


def _check_vendor_package(vendor: str) -> tuple[bool, str]:
    if vendor == 'choice':
        try:
            import EmQuantAPI  # noqa: F401
            return True, ''
        except ImportError:
            return False, '未安装 EmQuantAPI（需 Choice 终端环境）'
    elif vendor == 'ifind':
        try:
            import iFinDPy  # noqa: F401
            return True, ''
        except ImportError:
            return False, '未安装 iFinDPy（需 iFinD 终端环境）'
    elif vendor == 'wind':
        return False, '预留，尚未实现'
    else:
        return False, f'未知供应商：{vendor}'


class VendorAPIAdapter:
    """资讯供应商 API 统一适配器（Choice / iFind / Wind）"""

    def __init__(self, config_path: str | None = None):
        self._config_path = Path(config_path) if config_path else _CONFIG_PATH
        self._connected: dict[str, bool] = {}
        self._config: dict = {}
        self._load_config()

    def _load_config(self) -> None:
        if not self._config_path.exists():
            return
        try:
            cfg = yaml.safe_load(
                self._config_path.read_text(encoding='utf-8'),
            )
            ds = cfg.get('data_sources', {})
            self._config = ds.get('vendor_apis', {})
        except Exception:
            pass

    def _is_enabled(self, vendor: str) -> bool:
        vcfg = self._config.get(vendor, {})
        return vcfg.get('enabled', False)

    # ── 可用性检测 ────────────────────────────────────────

    def get_available_vendors(self) -> list[dict]:
        result = []
        for vendor in ('choice', 'ifind', 'wind'):
            enabled = self._is_enabled(vendor)
            if not enabled:
                result.append({
                    'name': vendor,
                    'available': False,
                    'connected': False,
                    'reason': '未启用（在 config.yaml data_sources.vendor_apis 中启用）',
                })
                continue

            installed, pkg_err = _check_vendor_package(vendor)
            if not installed:
                result.append({
                    'name': vendor,
                    'available': False,
                    'connected': False,
                    'reason': pkg_err,
                })
                continue

            result.append({
                'name': vendor,
                'available': True,
                'connected': self._connected.get(vendor, False),
                'reason': '',
            })
        return result

    # ── 连接管理 ──────────────────────────────────────────

    def connect(self, vendor: str) -> dict:
        if vendor == 'choice':
            return self._connect_choice()
        elif vendor == 'ifind':
            return self._connect_ifind()
        elif vendor == 'wind':
            return {'ok': False, 'error': 'Wind 适配器预留，尚未实现'}
        return {'ok': False, 'error': f'未知供应商：{vendor}'}

    def disconnect(self, vendor: str) -> dict:
        if vendor == 'choice':
            return self._disconnect_choice()
        elif vendor == 'ifind':
            return self._disconnect_ifind()
        elif vendor == 'wind':
            return {'ok': False, 'error': 'Wind 适配器预留'}
        return {'ok': False, 'error': f'未知供应商：{vendor}'}

    def _connect_choice(self) -> dict:
        installed, err = _check_vendor_package('choice')
        if not installed:
            return {'ok': False, 'error': err}
        try:
            from EmQuantAPI import c
            login_result = c.start()
            if login_result.ErrorCode != 0:
                return {
                    'ok': False,
                    'error': f'Choice 登录失败：{login_result.ErrorMsg}',
                }
            self._connected['choice'] = True
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': f'Choice 连接异常：{str(e)[:200]}'}

    def _disconnect_choice(self) -> dict:
        try:
            from EmQuantAPI import c
            c.stop()
        except Exception:
            pass
        self._connected['choice'] = False
        return {'ok': True}

    def _connect_ifind(self) -> dict:
        installed, err = _check_vendor_package('ifind')
        if not installed:
            return {'ok': False, 'error': err}
        try:
            from iFinDPy import THS_iFinDLogin
            vcfg = self._config.get('ifind', {})
            username = vcfg.get('username', '')
            password = _decode_password(vcfg.get('password', ''))
            result = THS_iFinDLogin(username, password)
            if result != 0:
                return {
                    'ok': False,
                    'error': f'iFinD 登录失败（错误码：{result}）',
                }
            self._connected['ifind'] = True
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': f'iFinD 连接异常：{str(e)[:200]}'}

    def _disconnect_ifind(self) -> dict:
        try:
            from iFinDPy import THS_iFinDLogout
            THS_iFinDLogout()
        except Exception:
            pass
        self._connected['ifind'] = False
        return {'ok': True}

    # ── 数据获取 ──────────────────────────────────────────

    def fetch_data(
        self,
        vendor: str,
        codes: list[str],
        fields: list[str],
        start_date: str = '',
        end_date: str = '',
        query_type: str = 'snapshot',
    ) -> dict:
        if not self._connected.get(vendor):
            return {'ok': False, 'error': f'{vendor} 未连接'}

        if vendor == 'choice':
            return self._fetch_choice(codes, fields, start_date, end_date, query_type)
        elif vendor == 'ifind':
            return self._fetch_ifind(codes, fields, start_date, end_date, query_type)
        elif vendor == 'wind':
            return {'ok': False, 'error': 'Wind 适配器预留'}
        return {'ok': False, 'error': f'未知供应商：{vendor}'}

    def _fetch_choice(
        self, codes, fields, start_date, end_date, query_type,
    ) -> dict:
        try:
            from EmQuantAPI import c
            t0 = time.time()

            codes_str = ','.join(codes)
            fields_str = ','.join(fields)

            if query_type == 'timeseries' and start_date and end_date:
                data = c.csd(codes_str, fields_str, start_date, end_date)
            else:
                data = c.css(codes_str, fields_str)

            if hasattr(data, 'ErrorCode') and data.ErrorCode != 0:
                return {
                    'ok': False,
                    'error': f'Choice 查询失败：{getattr(data, "ErrorMsg", "")}',
                }

            df = self._choice_result_to_df(data, codes, fields)
            elapsed = int((time.time() - t0) * 1000)

            return {
                'ok': True,
                'result': RemoteQueryResult(
                    df=df, row_count=len(df), col_count=len(df.columns),
                    query_time_ms=elapsed, source_name='choice',
                ),
            }
        except Exception as e:
            return {'ok': False, 'error': f'Choice 查询异常：{str(e)[:200]}'}

    def _choice_result_to_df(self, data, codes, fields) -> pd.DataFrame:
        if isinstance(data, pd.DataFrame):
            return data
        if hasattr(data, 'Data') and isinstance(data.Data, dict):
            return pd.DataFrame(data.Data)
        if hasattr(data, 'Codes') and hasattr(data, 'Data'):
            rows = []
            for i, code in enumerate(data.Codes):
                row = {'code': code}
                for j, fld in enumerate(data.Indicators):
                    idx = i * len(data.Indicators) + j
                    row[fld] = data.Data[idx] if idx < len(data.Data) else None
                rows.append(row)
            return pd.DataFrame(rows)
        return pd.DataFrame({'code': codes})

    def _fetch_ifind(
        self, codes, fields, start_date, end_date, query_type,
    ) -> dict:
        try:
            t0 = time.time()
            codes_str = ';'.join(codes)
            fields_str = ';'.join(fields)

            if query_type == 'timeseries' and start_date and end_date:
                from iFinDPy import THS_DateSerial
                data = THS_DateSerial(
                    codes_str, fields_str, '', start_date, end_date,
                )
            else:
                from iFinDPy import THS_Snapshot
                data = THS_Snapshot(codes_str, fields_str, '')

            df = self._ifind_result_to_df(data)
            elapsed = int((time.time() - t0) * 1000)

            return {
                'ok': True,
                'result': RemoteQueryResult(
                    df=df, row_count=len(df), col_count=len(df.columns),
                    query_time_ms=elapsed, source_name='ifind',
                ),
            }
        except Exception as e:
            return {'ok': False, 'error': f'iFinD 查询异常：{str(e)[:200]}'}

    def _ifind_result_to_df(self, data) -> pd.DataFrame:
        if isinstance(data, pd.DataFrame):
            return data
        if hasattr(data, 'data') and isinstance(data.data, pd.DataFrame):
            return data.data
        if hasattr(data, 'data') and isinstance(data.data, dict):
            return pd.DataFrame(data.data)
        return pd.DataFrame()

    # ── 统一导入 ──────────────────────────────────────────

    def import_vendor_data(
        self,
        vendor: str,
        codes: list[str],
        fields: list[str],
        local_table_name: str,
        table_type: str = 'unknown',
        date_tag: str | None = None,
        start_date: str = '',
        end_date: str = '',
        query_type: str = 'snapshot',
    ) -> dict:
        fetch_result = self.fetch_data(
            vendor, codes, fields,
            start_date, end_date, query_type,
        )
        if not fetch_result['ok']:
            return fetch_result

        rqr = fetch_result['result']
        source = f"vendor:{vendor}/{','.join(codes[:3])}"

        from tools.file_ingest import load_dataframe
        load_result = load_dataframe(
            df=rqr.df,
            table_name=local_table_name,
            table_type=table_type,
            date_tag=date_tag,
            source_info=source,
        )

        return {
            'ok': True,
            'table_name': load_result.table_name,
            'row_count': load_result.row_count,
            'col_count': load_result.col_count,
            'table_type': load_result.table_type,
            'query_time_ms': rqr.query_time_ms,
            'warnings': load_result.warnings,
        }


_adapter_instance: VendorAPIAdapter | None = None


def get_vendor_adapter(
    config_path: str | None = None,
) -> VendorAPIAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = VendorAPIAdapter(config_path)
    return _adapter_instance
