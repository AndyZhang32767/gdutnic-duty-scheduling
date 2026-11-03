"""Monthly field-duty (外勤) registrations, one record per member per month."""
from datetime import datetime

from server import db, schedule_store

TABLE = 'field_duty'


def init(conn):
    if isinstance(conn, db.MysqlConnection):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS field_duty ("
            " month CHAR(7) NOT NULL, username VARCHAR(64) NOT NULL,"
            " registered_at VARCHAR(40) NOT NULL, manual TINYINT NOT NULL DEFAULT 0,"
            " PRIMARY KEY(month, username)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin")
    else:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS field_duty ("
            " month TEXT NOT NULL, username TEXT NOT NULL, registered_at TEXT NOT NULL,"
            " manual INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(month, username))")
    db.upgrade_table(TABLE)


def _month(now=None):
    return (now or datetime.now(schedule_store.TZ)).strftime('%Y-%m')


def registered(username, month=None):
    with db.read() as conn:
        init(conn)
        return conn.execute(
            'SELECT registered_at FROM field_duty WHERE month=? AND username=?',
            (month or _month(), username)).fetchone() is not None


def member_status(username, month=None):
    month = month or _month()
    with db.read() as conn:
        init(conn)
        row = conn.execute(
            'SELECT registered_at FROM field_duty WHERE month=? AND username=?', (month, username)).fetchone()
        return {'month': month, 'registered': row is not None,
                'registered_at': row['registered_at'] if row else None}


def register(username, month=None):
    """Idempotent: registering twice in the same month keeps the original time."""
    month = month or _month()
    with db.write() as conn:
        init(conn)
        row = conn.execute(
            'SELECT registered_at FROM field_duty WHERE month=? AND username=?', (month, username)).fetchone()
        if row:
            return {'month': month, 'registered': True, 'registered_at': row['registered_at'], 'created': False}
        stamp = datetime.now(schedule_store.TZ).isoformat(timespec='seconds')
        conn.execute('INSERT INTO field_duty(month, username, registered_at) VALUES(?,?,?)',
                     (month, username, stamp))
        return {'month': month, 'registered': True, 'registered_at': stamp, 'created': True}


def overview(month=None):
    """Every ordinary account with the month's registration state."""
    month = month or _month()
    with db.read() as conn:
        init(conn)
        rows = conn.execute(
            'SELECT username, registered_at, manual FROM field_duty WHERE month=?', (month,)).fetchall()
        done = {row['username']: (row['registered_at'], bool(row['manual'])) for row in rows}
        accounts = [r['username'] for r in conn.execute(
            'SELECT username FROM member_accounts WHERE active=1 ORDER BY username')]
    items = [{'username': name, 'registered': name in done,
              'registered_at': done[name][0] if name in done else None,
              'manual': done[name][1] if name in done else False}
             for name in accounts]
    items.sort(key=lambda item: (not item['registered'], item['username']))
    return {'month': month, 'registered': len(done), 'total': len(items), 'items': items}


def set_participation(username, registered, month=None):
    """Administrator override: mark someone as having joined (or not) for the month."""
    month = month or _month()
    with db.write() as conn:
        init(conn)
        row = conn.execute('SELECT registered_at FROM field_duty WHERE month=? AND username=?',
                           (month, username)).fetchone()
        if registered:
            if row:
                # Keep the original timestamp; only flag the entry as manual.
                conn.execute('UPDATE field_duty SET manual=1 WHERE month=? AND username=?',
                             (month, username))
                return {'month': month, 'username': username, 'registered': True,
                        'registered_at': row['registered_at'], 'manual': True}
            stamp = datetime.now(schedule_store.TZ).isoformat(timespec='seconds')
            conn.execute('INSERT INTO field_duty(month, username, registered_at, manual)'
                         ' VALUES(?,?,?,1)', (month, username, stamp))
            return {'month': month, 'username': username, 'registered': True,
                    'registered_at': stamp, 'manual': True}
        conn.execute('DELETE FROM field_duty WHERE month=? AND username=?', (month, username))
        return {'month': month, 'username': username, 'registered': False,
                'registered_at': None, 'manual': False}
