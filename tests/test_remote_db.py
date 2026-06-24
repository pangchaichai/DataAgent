"""
tests/test_remote_db.py — 远程数据库管理测试

覆盖：
  - DBConnection dataclass + 序列化
  - 密码编解码（base64）
  - SQL 只读校验
  - RemoteDBManager 配置管理（CRUD + 持久化）
  - load_dataframe 统一入口
  - 驱动可用性检测
"""

import os
import sys

import pandas as pd
import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.remote_db import (
    DBConnection,
    RemoteDBManager,
    RemoteQueryResult,
    _decode_password,
    _encode_password,
    _validate_sql_readonly,
)


class TestPassword:
    def test_encode_empty(self):
        assert _encode_password('') == ''

    def test_encode_decode_roundtrip(self):
        pwd = '测试密码123!@#'
        encoded = _encode_password(pwd)
        assert encoded.startswith('base64:')
        assert _decode_password(encoded) == pwd

    def test_already_encoded(self):
        val = 'base64:dGVzdA=='
        assert _encode_password(val) == val

    def test_decode_plain(self):
        assert _decode_password('plaintext') == 'plaintext'

    def test_decode_empty(self):
        assert _decode_password('') == ''


class TestDBConnection:
    def test_to_dict(self):
        c = DBConnection(
            name='测试', db_type='mysql', host='localhost',
            port=3306, database='testdb', username='user',
            password='secret',
        )
        d = c.to_dict()
        assert d['name'] == '测试'
        assert d['read_only'] is True
        assert d['password'].startswith('base64:')

    def test_from_dict(self):
        d = {
            'name': 'pg', 'db_type': 'postgresql',
            'host': '10.0.0.1', 'port': 5432,
            'database': 'mydb', 'username': 'reader',
            'password': 'base64:c2VjcmV0',
        }
        c = DBConnection.from_dict(d)
        assert c.name == 'pg'
        assert c.password == 'secret'
        assert c.read_only is True

    def test_roundtrip(self):
        c = DBConnection(
            name='test', db_type='mysql', host='h', port=3306,
            database='db', username='u', password='p',
        )
        d = c.to_dict()
        c2 = DBConnection.from_dict(d)
        assert c2.name == c.name
        assert c2.db_type == c.db_type
        assert c2.password == c.password


class TestSQLValidation:
    def test_select_ok(self):
        ok, _ = _validate_sql_readonly('SELECT * FROM t')
        assert ok

    def test_with_cte_ok(self):
        ok, _ = _validate_sql_readonly('WITH cte AS (SELECT 1) SELECT * FROM cte')
        assert ok

    def test_insert_blocked(self):
        ok, err = _validate_sql_readonly('INSERT INTO t VALUES (1)')
        assert not ok
        assert 'INSERT' in err

    def test_drop_blocked(self):
        ok, _ = _validate_sql_readonly('DROP TABLE t')
        assert not ok

    def test_delete_blocked(self):
        ok, _ = _validate_sql_readonly('DELETE FROM t')
        assert not ok

    def test_update_blocked(self):
        ok, _ = _validate_sql_readonly('UPDATE t SET a=1')
        assert not ok

    def test_create_blocked(self):
        ok, _ = _validate_sql_readonly('CREATE TABLE t (a INT)')
        assert not ok


class TestRemoteQueryResult:
    def test_fields(self):
        df = pd.DataFrame({'a': [1, 2]})
        r = RemoteQueryResult(
            df=df, row_count=2, col_count=1,
            query_time_ms=50, source_name='test',
        )
        assert r.row_count == 2
        assert not r.truncated


class TestRemoteDBManager:
    def test_empty_config(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))
        assert mgr.list_connections() == []

    def test_save_and_list(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        conn = DBConnection(
            name='test_db', db_type='mysql',
            host='localhost', port=3306,
            database='testdb', username='root', password='pass',
        )
        result = mgr.save_connection(conn)
        assert result['ok']

        conns = mgr.list_connections()
        assert len(conns) == 1
        assert conns[0]['name'] == 'test_db'
        assert conns[0]['db_type'] == 'mysql'

    def test_save_persists_to_yaml(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        conn = DBConnection(
            name='pg_db', db_type='postgresql',
            host='10.0.0.1', port=5432,
            database='research', username='reader', password='pwd',
        )
        mgr.save_connection(conn)

        data = yaml.safe_load(cfg.read_text(encoding='utf-8'))
        dbs = data.get('data_sources', {}).get('remote_databases', [])
        assert len(dbs) == 1
        assert dbs[0]['name'] == 'pg_db'
        assert dbs[0]['password'].startswith('base64:')

    def test_delete_connection(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        mgr.save_connection(DBConnection(
            name='to_delete', db_type='mysql',
            host='h', database='db',
        ))
        assert len(mgr.list_connections()) == 1

        result = mgr.delete_connection('to_delete')
        assert result['ok']
        assert len(mgr.list_connections()) == 0

    def test_delete_nonexistent(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))
        result = mgr.delete_connection('no_such')
        assert not result['ok']

    def test_save_invalid_type(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        conn = DBConnection(name='bad', db_type='mongodb')
        result = mgr.save_connection(conn)
        assert not result['ok']

    def test_save_empty_name(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        conn = DBConnection(name='', db_type='mysql')
        result = mgr.save_connection(conn)
        assert not result['ok']

    def test_load_from_existing_config(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text(yaml.dump({
            'data_sources': {
                'remote_databases': [{
                    'name': 'pre_existing',
                    'db_type': 'postgresql',
                    'host': 'dbhost',
                    'port': 5432,
                    'database': 'mydb',
                    'username': 'u',
                    'password': 'base64:cHdk',
                }],
            },
        }, allow_unicode=True), encoding='utf-8')

        mgr = RemoteDBManager(str(cfg))
        conns = mgr.list_connections()
        assert len(conns) == 1
        assert conns[0]['name'] == 'pre_existing'

    def test_sqlite_connection_no_host(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        db_file = tmp_path / 'test.db'
        db_file.write_bytes(b'')

        conn = DBConnection(
            name='local_sqlite', db_type='sqlite',
            database=str(db_file),
        )
        result = mgr.save_connection(conn)
        assert result['ok']

    def test_test_connection_sqlite(self, tmp_path):
        import sqlite3
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        db_file = tmp_path / 'test.db'
        sconn = sqlite3.connect(str(db_file))
        sconn.execute('CREATE TABLE sample (id INTEGER, name TEXT)')
        sconn.execute("INSERT INTO sample VALUES (1, 'hello')")
        sconn.commit()
        sconn.close()

        conn = DBConnection(
            name='sqlite_test', db_type='sqlite',
            database=str(db_file),
        )
        result = mgr.test_connection(conn)
        assert result['ok']

    def test_list_tables_sqlite(self, tmp_path):
        import sqlite3
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        db_file = tmp_path / 'test.db'
        sconn = sqlite3.connect(str(db_file))
        sconn.execute('CREATE TABLE alpha (id INTEGER)')
        sconn.execute('CREATE TABLE beta (name TEXT)')
        sconn.commit()
        sconn.close()

        conn = DBConnection(
            name='sqlite_list', db_type='sqlite',
            database=str(db_file),
        )
        mgr.save_connection(conn)
        result = mgr.list_tables('sqlite_list')
        assert result['ok']
        names = {t['name'] for t in result['tables']}
        assert 'alpha' in names
        assert 'beta' in names

    def test_preview_table_sqlite(self, tmp_path):
        import sqlite3
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        db_file = tmp_path / 'test.db'
        sconn = sqlite3.connect(str(db_file))
        sconn.execute('CREATE TABLE data (val INTEGER)')
        for i in range(10):
            sconn.execute('INSERT INTO data VALUES (?)', (i,))
        sconn.commit()
        sconn.close()

        conn = DBConnection(
            name='sqlite_prev', db_type='sqlite',
            database=str(db_file),
        )
        mgr.save_connection(conn)
        result = mgr.preview_table('sqlite_prev', 'data', limit=5)
        assert result['ok']
        assert result['row_count'] == 5

    def test_fetch_query_sqlite(self, tmp_path):
        import sqlite3
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        db_file = tmp_path / 'test.db'
        sconn = sqlite3.connect(str(db_file))
        sconn.execute('CREATE TABLE nums (n INTEGER)')
        for i in range(5):
            sconn.execute('INSERT INTO nums VALUES (?)', (i * 10,))
        sconn.commit()
        sconn.close()

        conn = DBConnection(
            name='sqlite_q', db_type='sqlite',
            database=str(db_file),
        )
        mgr.save_connection(conn)
        result = mgr.fetch_query('sqlite_q', 'SELECT * FROM nums WHERE n > 10')
        assert result['ok']
        assert result['row_count'] == 3

    def test_fetch_query_rejects_insert(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        conn = DBConnection(
            name='no_write', db_type='sqlite',
            database=str(tmp_path / 'x.db'),
        )
        mgr.save_connection(conn)
        result = mgr.fetch_query('no_write', 'INSERT INTO t VALUES (1)')
        assert not result['ok']
        assert 'SELECT' in result['error'] or 'INSERT' in result['error']

    def test_import_to_local_sqlite(self, tmp_path):
        import sqlite3
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))

        db_file = tmp_path / 'source.db'
        sconn = sqlite3.connect(str(db_file))
        sconn.execute('CREATE TABLE holdings (product TEXT, market_value REAL)')
        sconn.execute("INSERT INTO holdings VALUES ('基金A', 1000000)")
        sconn.execute("INSERT INTO holdings VALUES ('基金B', 2000000)")
        sconn.commit()
        sconn.close()

        conn = DBConnection(
            name='import_src', db_type='sqlite',
            database=str(db_file),
        )
        mgr.save_connection(conn)

        result = mgr.import_to_local(
            'import_src', 'holdings',
            'remote_holdings', table_type='unknown',
        )
        assert result['ok']
        assert result['row_count'] == 2
        assert result['table_name'] == 'remote_holdings'

    def test_list_nonexistent_connection(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))
        result = mgr.list_tables('nonexistent')
        assert not result['ok']

    def test_preview_nonexistent_connection(self, tmp_path):
        cfg = tmp_path / 'config.yaml'
        cfg.write_text('app:\n  debug: false\n', encoding='utf-8')
        mgr = RemoteDBManager(str(cfg))
        result = mgr.preview_table('nonexistent', 'table')
        assert not result['ok']


class TestLoadDataframe:
    def test_basic_load(self):
        from tools.file_ingest import load_dataframe
        df = pd.DataFrame({'col_a': [1, 2, 3], 'col_b': ['x', 'y', 'z']})
        result = load_dataframe(df, 'test_df_load', source_info='test://unit')
        assert result.table_name == 'test_df_load'
        assert result.row_count == 3
        assert result.col_count == 2
        assert result.table_type == 'unknown'

    def test_with_table_type(self):
        from tools.file_ingest import load_dataframe
        df = pd.DataFrame({
            '持仓日期': ['2026-06-01'],
            '产品名称': ['基金A'],
            '资产市值_穿透后': [1000000],
        })
        result = load_dataframe(
            df, 'test_holding_df', table_type='holding',
            source_info='db:test.holdings',
        )
        assert result.table_name == 'test_holding_df'
        assert result.table_type == 'holding'

    def test_source_info_in_warnings(self):
        from tools.file_ingest import load_dataframe
        df = pd.DataFrame({'a': [1]})
        result = load_dataframe(
            df, 'test_src_info',
            source_info='db:投研库.sample_table',
        )
        assert any('数据来源' in w for w in result.warnings)
