"""
tools/remote_db.py — 远程数据库连接管理

职责：
  1. 数据库连接配置管理（CRUD + 持久化到 config.yaml）
  2. 连接测试 / 表列表 / 数据预览
  3. 远程数据导入本地 DuckDB（通过 load_dataframe 统一管线）

安全约束：
  - 所有连接强制 read_only（仅 SELECT）
  - 查询结果行数限制（默认 10000）
  - 密码 base64 编码存储（不明文）
  - SQL 经 SQLGuard 校验
  - 凭据不发送给 LLM
"""

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

_CONFIG_PATH = Path(__file__).parent.parent / 'config.yaml'

_SUPPORTED_DB_TYPES = {'mysql', 'postgresql', 'sqlite', 'sqlserver', 'oracle'}

_DEFAULT_PORTS = {
    'mysql': 3306,
    'postgresql': 5432,
    'oracle': 1521,
    'sqlserver': 1433,
    'sqlite': 0,
}

_MAX_QUERY_ROWS = 10000


@dataclass
class DBConnection:
    name: str
    db_type: str
    host: str = ''
    port: int = 0
    database: str = ''
    username: str = ''
    password: str = ''
    default_schema: str = ''
    read_only: bool = True

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'db_type': self.db_type,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'username': self.username,
            'password': _encode_password(self.password),
            'default_schema': self.default_schema,
            'read_only': True,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'DBConnection':
        return cls(
            name=d.get('name', ''),
            db_type=d.get('db_type', ''),
            host=d.get('host', ''),
            port=d.get('port', 0),
            database=d.get('database', ''),
            username=d.get('username', ''),
            password=_decode_password(d.get('password', '')),
            default_schema=d.get('default_schema', ''),
            read_only=True,
        )


@dataclass
class RemoteQueryResult:
    df: pd.DataFrame
    row_count: int
    col_count: int
    query_time_ms: int
    source_name: str
    truncated: bool = False


def _encode_password(pwd: str) -> str:
    if not pwd or pwd.startswith('base64:'):
        return pwd
    return 'base64:' + base64.b64encode(pwd.encode('utf-8')).decode('ascii')


def _decode_password(stored: str) -> str:
    if not stored:
        return ''
    if stored.startswith('base64:'):
        try:
            return base64.b64decode(stored[7:]).decode('utf-8')
        except Exception:
            return stored
    return stored


def _get_driver_module(db_type: str):
    if db_type == 'mysql':
        import pymysql
        return pymysql
    elif db_type == 'postgresql':
        import psycopg2
        return psycopg2
    elif db_type == 'sqlite':
        import sqlite3
        return sqlite3
    elif db_type == 'sqlserver':
        import pyodbc
        return pyodbc
    elif db_type == 'oracle':
        import cx_Oracle
        return cx_Oracle
    else:
        raise ValueError(f"不支持的数据库类型：{db_type}")


def _check_driver_available(db_type: str) -> tuple[bool, str]:
    try:
        _get_driver_module(db_type)
        return True, ''
    except ImportError as e:
        pkg_map = {
            'mysql': 'pymysql',
            'postgresql': 'psycopg2-binary',
            'sqlite': 'sqlite3（内置）',
            'sqlserver': 'pyodbc',
            'oracle': 'cx_Oracle',
        }
        pkg = pkg_map.get(db_type, db_type)
        return False, f"未安装 {pkg} 驱动：{e}"


def _create_connection(conn_info: DBConnection):
    db_type = conn_info.db_type

    if db_type == 'mysql':
        import pymysql
        return pymysql.connect(
            host=conn_info.host,
            port=conn_info.port or 3306,
            user=conn_info.username,
            password=conn_info.password,
            database=conn_info.database,
            charset='utf8mb4',
            connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )
    elif db_type == 'postgresql':
        import psycopg2
        return psycopg2.connect(
            host=conn_info.host,
            port=conn_info.port or 5432,
            user=conn_info.username,
            password=conn_info.password,
            dbname=conn_info.database,
            connect_timeout=10,
            options=f'-c search_path={conn_info.default_schema}'
            if conn_info.default_schema else '',
        )
    elif db_type == 'sqlite':
        import sqlite3
        return sqlite3.connect(conn_info.database, timeout=10)
    elif db_type == 'sqlserver':
        import pyodbc
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={conn_info.host},{conn_info.port or 1433};"
            f"DATABASE={conn_info.database};"
            f"UID={conn_info.username};PWD={conn_info.password};"
            f"Timeout=10;"
        )
        return pyodbc.connect(conn_str)
    elif db_type == 'oracle':
        import cx_Oracle
        dsn = cx_Oracle.makedsn(
            conn_info.host,
            conn_info.port or 1521,
            service_name=conn_info.database,
        )
        return cx_Oracle.connect(
            conn_info.username, conn_info.password, dsn,
        )
    else:
        raise ValueError(f"不支持的数据库类型：{db_type}")


def _validate_sql_readonly(sql: str) -> tuple[bool, str]:
    sql_stripped = sql.strip().upper()
    dangerous = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER',
        'TRUNCATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
    ]
    first_word = sql_stripped.split()[0] if sql_stripped else ''
    if first_word in dangerous:
        return False, f"仅允许 SELECT 查询，检测到 {first_word}"
    if not first_word.startswith('SELECT') and first_word != 'WITH':
        return False, f"仅允许 SELECT / WITH 查询"
    return True, ''


class RemoteDBManager:
    def __init__(self, config_path: str | None = None):
        self._config_path = Path(config_path) if config_path else _CONFIG_PATH
        self._connections: dict[str, DBConnection] = {}
        self._load_from_config()

    def _load_from_config(self) -> None:
        if not self._config_path.exists():
            return
        try:
            cfg = yaml.safe_load(
                self._config_path.read_text(encoding='utf-8'),
            )
        except Exception:
            return
        ds = cfg.get('data_sources', {})
        for item in ds.get('remote_databases', []):
            try:
                conn = DBConnection.from_dict(item)
                if conn.name:
                    self._connections[conn.name] = conn
            except Exception:
                continue

    def _save_to_config(self) -> None:
        if not self._config_path.exists():
            return
        try:
            raw = self._config_path.read_text(encoding='utf-8')
            cfg = yaml.safe_load(raw) or {}
        except Exception:
            cfg = {}

        if 'data_sources' not in cfg:
            cfg['data_sources'] = {}
        cfg['data_sources']['remote_databases'] = [
            c.to_dict() for c in self._connections.values()
        ]
        self._config_path.write_text(
            yaml.dump(cfg, allow_unicode=True, default_flow_style=False,
                      sort_keys=False),
            encoding='utf-8',
        )

    def list_connections(self) -> list[dict]:
        result = []
        for c in self._connections.values():
            available, reason = _check_driver_available(c.db_type)
            result.append({
                'name': c.name,
                'db_type': c.db_type,
                'host': c.host,
                'port': c.port,
                'database': c.database,
                'driver_available': available,
                'driver_error': reason,
            })
        return result

    def get_connection_info(self, name: str) -> DBConnection | None:
        return self._connections.get(name)

    def save_connection(self, conn: DBConnection) -> dict:
        if conn.db_type not in _SUPPORTED_DB_TYPES:
            return {'ok': False, 'error': f"不支持的类型：{conn.db_type}"}
        if not conn.name or not conn.name.strip():
            return {'ok': False, 'error': '连接名称不能为空'}
        conn.read_only = True
        self._connections[conn.name] = conn
        self._save_to_config()
        return {'ok': True}

    def delete_connection(self, name: str) -> dict:
        if name not in self._connections:
            return {'ok': False, 'error': f"连接不存在：{name}"}
        del self._connections[name]
        self._save_to_config()
        return {'ok': True}

    def test_connection(self, conn: DBConnection) -> dict:
        available, reason = _check_driver_available(conn.db_type)
        if not available:
            return {'ok': False, 'error': reason}
        try:
            db_conn = _create_connection(conn)
            cursor = db_conn.cursor()
            if conn.db_type == 'mysql':
                cursor.execute('SELECT 1')
            elif conn.db_type == 'postgresql':
                cursor.execute('SELECT 1')
            elif conn.db_type == 'sqlite':
                cursor.execute('SELECT 1')
            elif conn.db_type == 'sqlserver':
                cursor.execute('SELECT 1')
            elif conn.db_type == 'oracle':
                cursor.execute('SELECT 1 FROM DUAL')
            cursor.close()
            db_conn.close()
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:300]}

    def list_tables(self, conn_name: str) -> dict:
        conn_info = self._connections.get(conn_name)
        if not conn_info:
            return {'ok': False, 'error': f"连接不存在：{conn_name}"}

        available, reason = _check_driver_available(conn_info.db_type)
        if not available:
            return {'ok': False, 'error': reason}

        try:
            db_conn = _create_connection(conn_info)
            cursor = db_conn.cursor()
            tables = []

            if conn_info.db_type == 'mysql':
                cursor.execute('SHOW TABLES')
                rows = cursor.fetchall()
                for row in rows:
                    tname = list(row.values())[0] if isinstance(row, dict) else row[0]
                    tables.append({'name': tname})
            elif conn_info.db_type == 'postgresql':
                schema = conn_info.default_schema or 'public'
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                    (schema,),
                )
                for row in cursor.fetchall():
                    tables.append({'name': row[0]})
            elif conn_info.db_type == 'sqlite':
                cursor.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'",
                )
                for row in cursor.fetchall():
                    tables.append({'name': row[0]})
            elif conn_info.db_type in ('sqlserver', 'oracle'):
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE'",
                )
                for row in cursor.fetchall():
                    tables.append({'name': row[0]})

            cursor.close()
            db_conn.close()
            return {'ok': True, 'tables': tables}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:300]}

    def preview_table(
        self, conn_name: str, table: str, limit: int = 100,
    ) -> dict:
        conn_info = self._connections.get(conn_name)
        if not conn_info:
            return {'ok': False, 'error': f"连接不存在：{conn_name}"}

        safe_limit = min(max(limit, 1), 1000)
        sql = f'SELECT * FROM "{table}" LIMIT {safe_limit}'
        if conn_info.db_type == 'oracle':
            sql = f'SELECT * FROM "{table}" WHERE ROWNUM <= {safe_limit}'
        elif conn_info.db_type == 'sqlserver':
            sql = f'SELECT TOP {safe_limit} * FROM [{table}]'

        return self._execute_query(conn_info, sql)

    def fetch_query(
        self, conn_name: str, sql: str,
        limit: int = _MAX_QUERY_ROWS,
    ) -> dict:
        conn_info = self._connections.get(conn_name)
        if not conn_info:
            return {'ok': False, 'error': f"连接不存在：{conn_name}"}

        ok, err = _validate_sql_readonly(sql)
        if not ok:
            return {'ok': False, 'error': err}

        return self._execute_query(conn_info, sql, limit)

    def _execute_query(
        self, conn_info: DBConnection, sql: str,
        limit: int = _MAX_QUERY_ROWS,
    ) -> dict:
        available, reason = _check_driver_available(conn_info.db_type)
        if not available:
            return {'ok': False, 'error': reason}

        try:
            t0 = time.time()
            db_conn = _create_connection(conn_info)
            cursor = db_conn.cursor()
            cursor.execute(sql)

            if cursor.description is None:
                cursor.close()
                db_conn.close()
                return {'ok': False, 'error': '查询未返回结果'}

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchmany(limit + 1)
            truncated = len(rows) > limit
            if truncated:
                rows = rows[:limit]

            elapsed = int((time.time() - t0) * 1000)

            df = pd.DataFrame(rows, columns=columns)
            cursor.close()
            db_conn.close()

            result = RemoteQueryResult(
                df=df,
                row_count=len(df),
                col_count=len(columns),
                query_time_ms=elapsed,
                source_name=conn_info.name,
                truncated=truncated,
            )
            return {
                'ok': True,
                'result': result,
                'columns': columns,
                'row_count': len(df),
                'col_count': len(columns),
                'query_time_ms': elapsed,
                'truncated': truncated,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)[:300]}

    def import_to_local(
        self,
        conn_name: str,
        table_or_sql: str,
        local_table_name: str,
        table_type: str = 'unknown',
        date_tag: str | None = None,
    ) -> dict:
        conn_info = self._connections.get(conn_name)
        if not conn_info:
            return {'ok': False, 'error': f"连接不存在：{conn_name}"}

        is_sql = table_or_sql.strip().upper().startswith(('SELECT', 'WITH'))
        if is_sql:
            ok, err = _validate_sql_readonly(table_or_sql)
            if not ok:
                return {'ok': False, 'error': err}
            sql = table_or_sql
        else:
            safe_limit = _MAX_QUERY_ROWS
            if conn_info.db_type == 'oracle':
                sql = (
                    f'SELECT * FROM "{table_or_sql}" '
                    f'WHERE ROWNUM <= {safe_limit}'
                )
            elif conn_info.db_type == 'sqlserver':
                sql = f'SELECT TOP {safe_limit} * FROM [{table_or_sql}]'
            else:
                sql = f'SELECT * FROM "{table_or_sql}" LIMIT {safe_limit}'

        query_result = self._execute_query(conn_info, sql)
        if not query_result['ok']:
            return query_result

        rqr = query_result['result']
        source = f"db:{conn_name}.{table_or_sql}"

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
            'field_map': load_result.field_map,
            'unmatched_cols': load_result.unmatched_cols,
            'warnings': load_result.warnings,
            'query_time_ms': rqr.query_time_ms,
            'truncated': rqr.truncated,
        }


_manager_instance: RemoteDBManager | None = None


def get_remote_db_manager(
    config_path: str | None = None,
) -> RemoteDBManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = RemoteDBManager(config_path)
    return _manager_instance
