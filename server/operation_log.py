"""Operation log: who did what, and when.

Every meaningful write records one row here. The administrator page reads them back,
newest first. The table is created lazily so older databases upgrade themselves.
"""
from __future__ import annotations

from datetime import datetime

from server import db

TABLE = 'operation_log'


def init(conn):
    if isinstance(conn, db.MysqlConnection):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS operation_log ("
            " id BIGINT PRIMARY KEY AUTO_INCREMENT,"
            " at VARCHAR(40) NOT NULL, actor VARCHAR(64) NOT NULL,"
            " role VARCHAR(16) NOT NULL DEFAULT '', action VARCHAR(64) NOT NULL,"
            " detail TEXT NOT NULL,"
            " INDEX idx_operation_log_at (at)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin")
    else:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS operation_log ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " at TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL DEFAULT '',"
            " action TEXT NOT NULL, detail TEXT NOT NULL)")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_operation_log_at ON operation_log(at)')


def _clock():
    from server import system_clock
    return system_clock.now()


def record(actor, action, detail='', role=''):
    """Append one log line. Never raises: logging must not break the operation."""
    try:
        with db.write() as conn:
            init(conn)
            conn.execute(
                'INSERT INTO operation_log(at,actor,role,action,detail) VALUES(?,?,?,?,?)',
                (_clock().isoformat(timespec='seconds'), str(actor or '匿名')[:64],
                 str(role or '')[:16], str(action)[:64], str(detail or '')[:2000]))
    except Exception as exc:  # pragma: no cover - defensive
        print(f'[log] 写入操作日志失败: {type(exc).__name__}: {exc}')


def list_entries(limit=300, actor='', action=''):
    """Newest first, optionally filtered by account or action keyword."""
    limit = max(1, min(int(limit), 1000))
    with db.read() as conn:
        init(conn)
        sql = 'SELECT at,actor,role,action,detail FROM operation_log'
        args = []
        clauses = []
        if actor:
            clauses.append('actor=?')
            args.append(actor)
        if action:
            clauses.append('(action LIKE ? OR detail LIKE ?)')
            args.extend([f'%{action}%', f'%{action}%'])
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY id DESC LIMIT ?'
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    return [dict(row) for row in rows]


def actors():
    with db.read() as conn:
        init(conn)
        return [row['actor'] for row in conn.execute(
            'SELECT DISTINCT actor FROM operation_log ORDER BY actor').fetchall()]
