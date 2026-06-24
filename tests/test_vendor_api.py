"""
tests/test_vendor_api.py — 金融资讯 API 适配器测试（Mock）

Choice / iFind / Wind 均为 Windows-only + 需付费终端授权，
此处使用 Mock 测试覆盖适配器逻辑。
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.vendor_api import (
    VendorAPIAdapter,
    VendorStatus,
    _check_vendor_package,
    get_vendor_adapter,
)


class TestCheckVendorPackage:
    def test_choice_not_installed(self):
        available, reason = _check_vendor_package('choice')
        assert not available
        assert 'EmQuantAPI' in reason

    def test_ifind_not_installed(self):
        available, reason = _check_vendor_package('ifind')
        assert not available
        assert 'iFinDPy' in reason

    def test_wind_reserved(self):
        available, reason = _check_vendor_package('wind')
        assert not available
        assert '预留' in reason

    def test_unknown_vendor(self):
        available, reason = _check_vendor_package('bloomberg')
        assert not available
        assert '未知' in reason


class TestVendorAPIAdapter:
    def _make_adapter(self, tmp_path, vendor_config=None):
        cfg = tmp_path / 'config.yaml'
        data = {'data_sources': {'vendor_apis': vendor_config or {}}}
        cfg.write_text(yaml.dump(data, allow_unicode=True), encoding='utf-8')
        return VendorAPIAdapter(str(cfg))

    def test_get_available_all_disabled(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        vendors = adapter.get_available_vendors()
        assert len(vendors) == 3
        for v in vendors:
            assert not v['available']

    def test_get_available_choice_enabled_no_package(self, tmp_path):
        adapter = self._make_adapter(tmp_path, {'choice': {'enabled': True}})
        vendors = adapter.get_available_vendors()
        choice = next(v for v in vendors if v['name'] == 'choice')
        assert not choice['available']
        assert 'EmQuantAPI' in choice['reason']

    def test_get_available_ifind_enabled_no_package(self, tmp_path):
        adapter = self._make_adapter(tmp_path, {'ifind': {'enabled': True}})
        vendors = adapter.get_available_vendors()
        ifind = next(v for v in vendors if v['name'] == 'ifind')
        assert not ifind['available']
        assert 'iFinDPy' in ifind['reason']

    def test_wind_always_reserved(self, tmp_path):
        adapter = self._make_adapter(tmp_path, {'wind': {'enabled': True}})
        vendors = adapter.get_available_vendors()
        wind = next(v for v in vendors if v['name'] == 'wind')
        assert not wind['available']
        assert '预留' in wind['reason']

    def test_connect_wind_returns_error(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.connect('wind')
        assert not result['ok']
        assert '预留' in result['error']

    def test_connect_unknown_vendor(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.connect('bloomberg')
        assert not result['ok']

    def test_disconnect_wind(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.disconnect('wind')
        assert not result['ok']

    def test_fetch_not_connected(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.fetch_data('choice', ['000001.SZ'], ['close'])
        assert not result['ok']
        assert '未连接' in result['error']

    def test_fetch_wind_reserved(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        adapter._connected['wind'] = True
        result = adapter.fetch_data('wind', ['000001.SZ'], ['close'])
        assert not result['ok']
        assert '预留' in result['error']

    @patch('tools.vendor_api._check_vendor_package', return_value=(True, ''))
    def test_connect_choice_mock(self, mock_check, tmp_path):
        adapter = self._make_adapter(tmp_path, {'choice': {'enabled': True}})
        mock_c = MagicMock()
        mock_login = MagicMock()
        mock_login.ErrorCode = 0
        mock_c.start.return_value = mock_login

        with patch.dict('sys.modules', {'EmQuantAPI': MagicMock(c=mock_c)}):
            result = adapter.connect('choice')
        assert result['ok']
        assert adapter._connected.get('choice')

    @patch('tools.vendor_api._check_vendor_package', return_value=(True, ''))
    def test_connect_choice_login_failure(self, mock_check, tmp_path):
        adapter = self._make_adapter(tmp_path, {'choice': {'enabled': True}})
        mock_c = MagicMock()
        mock_login = MagicMock()
        mock_login.ErrorCode = -1
        mock_login.ErrorMsg = '终端未运行'
        mock_c.start.return_value = mock_login

        with patch.dict('sys.modules', {'EmQuantAPI': MagicMock(c=mock_c)}):
            result = adapter.connect('choice')
        assert not result['ok']
        assert '登录失败' in result['error']

    @patch('tools.vendor_api._check_vendor_package', return_value=(True, ''))
    def test_connect_ifind_mock(self, mock_check, tmp_path):
        adapter = self._make_adapter(tmp_path, {
            'ifind': {'enabled': True, 'username': 'user', 'password': 'pass'},
        })
        mock_login = MagicMock(return_value=0)

        with patch.dict('sys.modules', {
            'iFinDPy': MagicMock(THS_iFinDLogin=mock_login),
        }):
            result = adapter.connect('ifind')
        assert result['ok']
        assert adapter._connected.get('ifind')

    @patch('tools.vendor_api._check_vendor_package', return_value=(True, ''))
    def test_connect_ifind_login_failure(self, mock_check, tmp_path):
        adapter = self._make_adapter(tmp_path, {
            'ifind': {'enabled': True, 'username': 'u', 'password': 'p'},
        })
        mock_login = MagicMock(return_value=-1)

        with patch.dict('sys.modules', {
            'iFinDPy': MagicMock(THS_iFinDLogin=mock_login),
        }):
            result = adapter.connect('ifind')
        assert not result['ok']
        assert '登录失败' in result['error']

    def test_fetch_choice_snapshot(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        adapter._connected['choice'] = True

        mock_css_result = MagicMock()
        mock_css_result.ErrorCode = 0
        mock_css_result.Codes = ['000001.SZ']
        mock_css_result.Indicators = ['CLOSE']
        mock_css_result.Data = [15.5]

        mock_c = MagicMock()
        mock_c.css.return_value = mock_css_result

        with patch.dict('sys.modules', {'EmQuantAPI': MagicMock(c=mock_c)}):
            result = adapter.fetch_data(
                'choice', ['000001.SZ'], ['CLOSE'],
                query_type='snapshot',
            )
        assert result['ok']
        assert result['result'].row_count == 1

    def test_fetch_choice_timeseries(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        adapter._connected['choice'] = True

        mock_data = pd.DataFrame({
            'code': ['000001.SZ'] * 3,
            'date': ['2026-06-01', '2026-06-02', '2026-06-03'],
            'close': [15.5, 15.8, 16.0],
        })

        mock_c = MagicMock()
        mock_c.csd.return_value = mock_data

        with patch.dict('sys.modules', {'EmQuantAPI': MagicMock(c=mock_c)}):
            result = adapter.fetch_data(
                'choice', ['000001.SZ'], ['close'],
                start_date='2026-06-01', end_date='2026-06-03',
                query_type='timeseries',
            )
        assert result['ok']
        assert result['result'].row_count == 3

    def test_fetch_ifind_snapshot(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        adapter._connected['ifind'] = True

        mock_result = MagicMock()
        mock_result.data = pd.DataFrame({
            'code': ['000001.SZ'],
            'close': [15.5],
        })

        mock_ths = MagicMock(return_value=mock_result)

        with patch.dict('sys.modules', {
            'iFinDPy': MagicMock(THS_Snapshot=mock_ths),
        }):
            result = adapter.fetch_data(
                'ifind', ['000001.SZ'], ['close'],
                query_type='snapshot',
            )
        assert result['ok']
        assert result['result'].row_count == 1

    def test_import_vendor_data(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        adapter._connected['choice'] = True

        mock_data = pd.DataFrame({
            'code': ['000001.SZ', '000002.SZ'],
            'close': [15.5, 20.0],
        })
        mock_c = MagicMock()
        mock_c.css.return_value = mock_data

        with patch.dict('sys.modules', {'EmQuantAPI': MagicMock(c=mock_c)}):
            result = adapter.import_vendor_data(
                'choice', ['000001.SZ', '000002.SZ'], ['close'],
                local_table_name='vendor_prices',
            )
        assert result['ok']
        assert result['row_count'] == 2
        assert result['table_name'] == 'vendor_prices'

    def test_import_not_connected(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.import_vendor_data(
            'choice', ['000001.SZ'], ['close'],
            local_table_name='test',
        )
        assert not result['ok']

    def test_no_config_file(self, tmp_path):
        adapter = VendorAPIAdapter(str(tmp_path / 'nonexistent.yaml'))
        vendors = adapter.get_available_vendors()
        assert len(vendors) == 3
        for v in vendors:
            assert not v['available']

    def test_disconnect_choice_cleanup(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        adapter._connected['choice'] = True

        with patch.dict('sys.modules', {'EmQuantAPI': MagicMock()}):
            result = adapter.disconnect('choice')
        assert result['ok']
        assert not adapter._connected.get('choice')

    def test_disconnect_ifind_cleanup(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        adapter._connected['ifind'] = True

        with patch.dict('sys.modules', {'iFinDPy': MagicMock()}):
            result = adapter.disconnect('ifind')
        assert result['ok']
        assert not adapter._connected.get('ifind')


class TestVendorStatus:
    def test_dataclass(self):
        s = VendorStatus(name='choice', available=True, connected=False, reason='')
        assert s.name == 'choice'
        assert s.available
        assert not s.connected
