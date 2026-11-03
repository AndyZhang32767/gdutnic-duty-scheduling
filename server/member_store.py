"""Duty accounts. Administrators are accounts that carry the schedule/accounts/field permissions."""
from server import admin_store, db, permissions as perms_store, weekly_store

INITIAL_PASSWORD = 'gg2017'


def provision():
    """Create missing roster accounts; never reset an existing password."""
    roster = weekly_store.load()
    names = {name for slot in roster['slots'] for day in slot['days'] for name in day}
    with db.read() as conn:
        names.update(r['name'] for r in conn.execute('SELECT DISTINCT name FROM attendance'))
    return create_missing(names)


def create_missing(names):
    names = sorted({n.strip() for n in names if isinstance(n, str) and n.strip()})
    if any(len(n) > 64 for n in names):
        raise ValueError('姓名不能超过 64 字')
    created = 0
    with db.write() as conn:
        existing = {row['username'] for row in conn.execute('SELECT username FROM member_accounts')}
        missing = [name for name in names if name not in existing]
        # Hash once per run: every new account starts with the same initial password.
        if missing:
            hashed = admin_store._hash_password(INITIAL_PASSWORD)
            conn.executemany('INSERT INTO member_accounts(username,password,active) VALUES(?,?,1)',
                             [(name, hashed) for name in missing])
            created = len(missing)
    return {'created': created, 'existing': len(names) - created}


def create(name, password=None):
    name = str(name or '').strip()
    if not name or len(name) > 64:
        raise ValueError('请填写姓名，最多 64 字')
    if password is not None and (len(password) < 6 or len(password) > 128):
        raise ValueError('密码长度应为 6～128 位')
    with db.write() as conn:
        if conn.execute('SELECT username FROM member_accounts WHERE username=?', (name,)).fetchone():
            raise ValueError('该姓名账号已存在')
        conn.execute('INSERT INTO member_accounts(username,password,active,permissions) VALUES(?,?,1,?)',
                     (name, admin_store._hash_password(password or INITIAL_PASSWORD),
                      perms_store.encode(perms_store.DEFAULT_PERMISSIONS)))
    return {'created': 1, 'existing': 0}


def delete(name):
    from server.security import MEMBER_SESSIONS
    with db.write() as conn:
        if not conn.execute('DELETE FROM member_accounts WHERE username=?', (name,)).rowcount:
            raise LookupError('账号不存在')
    MEMBER_SESSIONS.clear(name + ':')


def list_accounts():
    with db.read() as conn:
        rows = [dict(r) for r in conn.execute(
            'SELECT username,active,permissions FROM member_accounts ORDER BY username')]
    for row in rows:
        row['permissions'] = sorted(perms_store.decode(row.get('permissions')))
    return rows


def authenticate(name, password):
    with db.read() as conn:
        row = conn.execute('SELECT password,active FROM member_accounts WHERE username=?', (name,)).fetchone()
    if row and row['active'] and admin_store._verify_password(password, row['password']):
        import hashlib
        return hashlib.sha256(row['password'].encode()).hexdigest()
    return None


def verify(name, password):
    return authenticate(name, password) is not None


def session_valid(name, version):
    # Changing/resetting a password invalidates pre-existing member sessions. The cache
    # key includes the stored digest, so a new password simply misses the old entry.
    import hashlib
    from server.security import MEMBER_SESSIONS
    key = f'{name}:{version}'
    cached = MEMBER_SESSIONS.get(key)
    if cached is not None:
        return cached
    with db.read() as conn:
        row = conn.execute('SELECT password,active FROM member_accounts WHERE username=?', (name,)).fetchone()
    valid = bool(row and row['active'] and version == hashlib.sha256(row['password'].encode()).hexdigest())
    MEMBER_SESSIONS.put(key, valid)
    return valid


def session_version(name):
    import hashlib
    with db.read() as conn:
        row = conn.execute('SELECT password FROM member_accounts WHERE username=?', (name,)).fetchone()
    return hashlib.sha256(row['password'].encode()).hexdigest()


def update(name, active=None, reset=False):
    from server.security import MEMBER_SESSIONS
    with db.write() as conn:
        if not conn.execute('SELECT username FROM member_accounts WHERE username=?', (name,)).fetchone():
            raise ValueError('账号不存在')
        if active is not None:
            conn.execute('UPDATE member_accounts SET active=? WHERE username=?', (int(bool(active)), name))
        if reset:
            conn.execute('UPDATE member_accounts SET password=? WHERE username=?',
                         (admin_store._hash_password(INITIAL_PASSWORD), name))
    MEMBER_SESSIONS.clear(name + ':')


def set_password(name, new_password):
    """Administrator-side password change; no old password required."""
    from server.security import MEMBER_SESSIONS
    if len(new_password) < 6 or len(new_password) > 128:
        raise ValueError('新密码长度应为 6～128 位')
    with db.write() as conn:
        if not conn.execute('UPDATE member_accounts SET password=? WHERE username=?',
                            (admin_store._hash_password(new_password), name)).rowcount:
            raise LookupError('账号不存在')
    MEMBER_SESSIONS.clear(name + ':')


def change_password(name, old_password, new_password):
    from server.security import MEMBER_SESSIONS
    if len(new_password) < 6 or len(new_password) > 128:
        raise ValueError('新密码长度应为 6～128 位')
    with db.write() as conn:
        row = conn.execute('SELECT password,active FROM member_accounts WHERE username=?', (name,)).fetchone()
        if not row or not row['active'] or not admin_store._verify_password(old_password, row['password']):
            raise ValueError('当前密码不正确')
        conn.execute('UPDATE member_accounts SET password=? WHERE username=?',
                     (admin_store._hash_password(new_password), name))
    MEMBER_SESSIONS.clear(name + ':')
