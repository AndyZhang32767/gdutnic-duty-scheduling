"""Permission groups for every account (ordinary duty accounts and administrators).

Each account carries a set of permissions. Administrators were previously a separate
table; they are migrated into member accounts as a member holding ``admin`` so a single
account list can be edited, including administrator accounts.
"""
from __future__ import annotations

from server import admin_store, db

# Permission ids are stable identifiers; labels are shown in the UI.
# `accounts` (operate) covers reset/disable/enable; adding and deleting accounts is a
# separate leaf so the two can be granted independently.
PERMISSIONS = {
    'user': ('用户界面', '登录用户页面，查看自己的排班并签到'),
    'schedule': ('更改排班', '每日、每周、特殊排班以及其他设置'),
    'accounts': ('操作账号', '重置密码、停用或启用账号'),
    'accounts_manage': ('添加/删除账号', '新建账号、删除账号'),
    'accounts_protected': ('更改权限', '为他人分配权限；无此权限者不能删除、停用、重置或更改有权限者的密码'),
    'field': ('外勤管理', '查看外勤统计、管理外勤登记'),
}
ALL_PERMISSIONS = tuple(PERMISSIONS)
DEFAULT_PERMISSIONS = ('user',)

# Legacy administrator accounts get the full administrative set on first use.
ADMIN_DEFAULTS = ALL_PERMISSIONS

# Tree shown in the permission editor. Node ids that are not permission ids are groups:
# ticking a group selects all of its leaves, and a parent mirrors its children.
TREE = [
    {'id': 'user', 'label': '用户界面', 'hint': '登录用户页面，查看自己的排班并签到'},
    {'id': 'admin', 'label': '管理员', 'hint': '可进入管理端；以下能力随勾选生效', 'children': [
        {'id': 'schedule', 'label': '更改排班', 'hint': '每日、每周、特殊排班与其他设置'},
        {'id': 'accounts_group', 'label': '用户管理', 'hint': '', 'children': [
            {'id': 'accounts', 'label': '操作账号', 'hint': '重置密码、停用或启用账号'},
            {'id': 'accounts_manage', 'label': '添加/删除账号', 'hint': '新建和删除账号'},
            {'id': 'accounts_protected', 'label': '更改权限', 'hint': '为他人分配权限；有权限的账号受保护'},
        ]},
        {'id': 'field', 'label': '外勤管理', 'hint': '外勤统计与登记'},
    ]},
]
# Ids used only for grouping; they are never stored.
GROUP_IDS = ('admin', 'accounts_group')


def leaves(nodes=None):
    """All permission ids reachable from the tree."""
    found = []
    for node in (TREE if nodes is None else nodes):
        if node['id'] in GROUP_IDS:
            found.extend(leaves(node.get('children') or []))
        else:
            found.append(node['id'])
    return found


def _clean(values):
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(v) for v in values if str(v) in PERMISSIONS}


def encode(values):
    """Stable storage format for a permission set."""
    return ','.join(sorted(_clean(values)))


def decode(stored):
    if not stored:
        return set()
    return _clean(str(stored).split(','))


def permissions_of(name):
    with db.read() as conn:
        row = conn.execute('SELECT permissions FROM member_accounts WHERE username=?', (name,)).fetchone()
    return decode(row['permissions']) if row else set()


def has(name, permission):
    return permission in permissions_of(name)


ADMIN_PERMISSIONS = frozenset(leaves(TREE)) - {'user'}


def is_admin(name):
    """Any account allowed to use the administrator pages."""
    return bool(permissions_of(name) & ADMIN_PERMISSIONS)


def can_admin(name):
    return is_admin(name)


def set_permissions(name, values):
    drop_cache(name)
    perms = encode(values)
    with db.write() as conn:
        if not conn.execute('UPDATE member_accounts SET permissions=? WHERE username=?',
                            (perms, name)).rowcount:
            raise LookupError('账号不存在')
    return decode(perms)


def drop_cache(name):
    from server.security import MEMBER_SESSIONS
    MEMBER_SESSIONS.clear(name + ':')


def ensure_defaults():
    """Migrate legacy administrator rows and fill missing permission columns."""
    # Read the legacy list before opening the write transaction (nested locks deadlock).
    legacy_admins = set(admin_store.usernames())
    with db.write() as conn:
        rows = conn.execute("SELECT username FROM member_accounts WHERE permissions IS NULL OR permissions=''").fetchall()
        for row in rows:
            # Accounts that were administrators before the permission model keep full rights.
            grant = ADMIN_DEFAULTS if row['username'] in legacy_admins else DEFAULT_PERMISSIONS
            conn.execute('UPDATE member_accounts SET permissions=? WHERE username=?',
                         (encode(grant), row['username']))
        # Every legacy administrator becomes an account with every permission, so the
        # console login keeps working with the same password hash.
        for legacy in conn.execute('SELECT username,password FROM users').fetchall():
            existing = conn.execute('SELECT username,password FROM member_accounts WHERE username=?',
                                    (legacy['username'],)).fetchone()
            if existing:
                conn.execute('UPDATE member_accounts SET permissions=? WHERE username=?',
                             (encode(ADMIN_DEFAULTS), legacy['username']))
            else:
                conn.execute(
                    'INSERT INTO member_accounts(username,password,active,permissions) VALUES(?,?,1,?)',
                    (legacy['username'], legacy['password'], encode(ADMIN_DEFAULTS)))
