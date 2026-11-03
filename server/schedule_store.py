"""Persistent duty schedules and atomic, repeat-safe attendance."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from server import db

TZ = ZoneInfo('Asia/Shanghai')


def init(conn):
    # Schema is initialized at connection time, outside all business transactions.
    pass


def shift_bounds(shift):
    start = datetime.fromisoformat(f"{shift['day']}T{shift['start']}:00").replace(tzinfo=TZ)
    end = datetime.fromisoformat(f"{shift['day']}T{shift['end']}:00").replace(tzinfo=TZ)
    if end < start:
        end += timedelta(days=1)
    return start, end


def list_day(day, name=None):
    previous = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    with db.read() as conn:
        init(conn)
        result = []
        sql = "SELECT * FROM shifts WHERE (day=? OR (day=? AND end < start AND end > '00:00'))"
        args = [day, previous]
        if name is not None:
            sql += ' AND EXISTS (SELECT 1 FROM attendance WHERE shift_id=shifts.id AND name=?)'
            args.append(name)
        rows = conn.execute(sql + ' ORDER BY day,start,id', args).fetchall()
        grouped = _members_many(conn, [row['id'] for row in rows], name)
        for row in rows:
            item = dict(row)
            item['members'] = grouped.get(row['id'], [])
            result.append(item)
        _attach_status(result, name)
        return result


def _members_many(conn, shift_ids, name=None):
    """Load attendance for several shifts at once instead of one query per shift."""
    grouped = {}
    if not shift_ids:
        return grouped
    placeholders = ','.join('?' for _ in shift_ids)
    sql = f'SELECT shift_id,name,checked_at FROM attendance WHERE shift_id IN ({placeholders})'
    args = list(shift_ids)
    if name is not None:
        sql += ' AND name=?'
        args.append(name)
    for row in conn.execute(sql + ' ORDER BY shift_id,name', args):
        grouped.setdefault(row['shift_id'], []).append(
            {'name': row['name'], 'checked_at': row['checked_at']})
    return grouped


def _attach_status(items, name=None):
    """Add late/absent/pending status for the member view, using the configured rules."""
    if not items:
        return
    from server import duty_settings
    rules = duty_settings.load()
    now = datetime.now(TZ)
    for item in items:
        start, end = shift_bounds(item)
        late_at = start + timedelta(minutes=rules['late_minutes'])
        absent_at = start + timedelta(minutes=rules['absent_minutes'])
        for member in item['members']:
            checked = member.get('checked_at')
            if checked:
                try:
                    at = datetime.fromisoformat(str(checked))
                except ValueError:
                    member['status'] = 'normal'
                    continue
                if at.tzinfo is None:
                    at = at.replace(tzinfo=TZ)
                # Already checked in: the label stays "已签到"; only the colour changes.
                member['status'] = 'absent' if at >= absent_at else 'late' if at > late_at else 'normal'
            elif now >= end:
                # Only a finished shift can make an unchecked member absent.
                member['status'] = 'absent'
            else:
                # Unchecked and still running (or upcoming): keep it neutral.
                member['status'] = 'pending'


def validate_shift(body):
    if not isinstance(body, dict):
        raise ValueError("排班数据必须为对象")
    day = str(body.get('day', ''))
    date.fromisoformat(day)
    start, end = str(body.get('start', '')), str(body.get('end', ''))
    for value in (start, end):
        datetime.strptime(value, '%H:%M')
        if len(value) != 5:
            raise ValueError('时间格式应为 HH:MM')
    if start == end:
        raise ValueError('开始和结束时间不能相同；结束早于开始时表示次日结束')
    location = str(body.get('location', '')).strip()
    note = str(body.get('note', '')).strip()
    members = body.get('members')
    if not isinstance(members, list) or not members or len(members) > 100:
        raise ValueError('请填写 1–100 位值班人员')
    if any(not isinstance(n, str) or not n.strip() or len(n.strip()) > 40 for n in members):
        raise ValueError('人员姓名不能为空且不能超过 40 字')
    names = list(dict.fromkeys(n.strip() for n in members))
    if len(location) > 120 or len(note) > 500:
        raise ValueError('地点最多 120 字，备注最多 500 字')
    return day, start, end, location, note, names


def save(body, shift_id=None):
    day, start, end, location, note, names = validate_shift(body)
    special = int(bool(body.get('special')))
    with db.write() as conn:
        init(conn)
        if shift_id is None:
            shift_id = conn.execute(
                'INSERT INTO shifts(day,start,end,location,note,special) VALUES(?,?,?,?,?,?)',
                (day, start, end, location, note, special)).lastrowid
        else:
            old = conn.execute('SELECT * FROM shifts WHERE id=?', (shift_id,)).fetchone()
            if not old:
                raise LookupError('班次不存在')
            special = int(old['special'])
            checked = [r['name'] for r in conn.execute(
                'SELECT name FROM attendance WHERE shift_id=? AND checked_at IS NOT NULL', (shift_id,))]
            if checked and (any(n not in names for n in checked) or any(old[k] != v for k, v in
                            [('day', day), ('start', start), ('end', end)])):
                raise ValueError('已有签到，不能更改日期、时间或移除已签到人员')
            conn.execute('UPDATE shifts SET day=?,start=?,end=?,location=?,note=?,special=? WHERE id=?',
                         (day, start, end, location, note, special, shift_id))
        existing = {row['name'] for row in conn.execute(
            'SELECT name FROM attendance WHERE shift_id=?', (shift_id,)).fetchall()}
        removed = [(shift_id, existing_name) for existing_name in existing if existing_name not in names]
        if removed:
            conn.executemany('DELETE FROM attendance WHERE shift_id=? AND name=?', removed)
        missing = [(shift_id, person) for person in names if person not in existing]
        if missing:
            conn.executemany('INSERT INTO attendance(shift_id,name) VALUES(?,?)', missing)
    return shift_id


def delete(shift_id):
    with db.write() as conn:
        init(conn)
        if not conn.execute('DELETE FROM shifts WHERE id=?', (shift_id,)).rowcount:
            raise LookupError('班次不存在')


def list_special(from_day=None, name=None):
    """Upcoming one-off shifts, excluding shifts already covered by their day list."""
    with db.read() as conn:
        init(conn)
        sql = 'SELECT * FROM shifts WHERE special=1'
        args = []
        if from_day:
            date.fromisoformat(from_day)
            sql += ' AND day>=?'
            args.append(from_day)
        if name is not None:
            sql += ' AND EXISTS (SELECT 1 FROM attendance WHERE shift_id=shifts.id AND name=?)'
            args.append(name)
        rows = conn.execute(sql + ' ORDER BY day,start,id', args).fetchall()
        grouped = _members_many(conn, [row['id'] for row in rows], name)
        return [{**dict(row), 'members': grouped.get(row['id'], [])} for row in rows]


def _members(conn, shift_id, name=None):
    sql = 'SELECT name,checked_at FROM attendance WHERE shift_id=?'
    args = [shift_id]
    if name is not None:
        sql += ' AND name=?'
        args.append(name)
    return [dict(r) for r in conn.execute(sql + ' ORDER BY name', args)]


def clear_all():
    with db.write() as conn:
        deleted = conn.execute('DELETE FROM shifts').rowcount
    return {'deleted': deleted}


def check_in(shift_id, name):
    stamp, chained = check_in_with_chain(shift_id, name)
    return stamp


def check_in_with_chain(shift_id, name, now=None):
    """Check in, then auto-check the next shift of the same pair (1→2 or 3→4).

    Only the second shift of a same-day pair is auto-checked, and only when it starts
    exactly when the first ends. 2→3 and 4→next day's 1 are never chained. The original
    instant is reused so the partner shift counts as on-time, while the shift the person
    actually tapped keeps its own late/absent classification.
    """
    from server import duty_settings
    now = now or datetime.now(TZ)
    with db.write() as conn:
        init(conn)
        row = conn.execute('''SELECT a.checked_at,s.day,s.start,s.end FROM attendance a
            JOIN shifts s ON s.id=a.shift_id WHERE a.shift_id=? AND a.name=?''', (shift_id, name)).fetchone()
        if not row:
            raise LookupError('未找到该班次或排班人员')
        start, end = shift_bounds(row)
        early = timedelta(minutes=duty_settings.load()['early_minutes'])
        if not row['checked_at'] and not start - early <= now < end:
            raise ValueError(f'仅可在班次开始前 {early.seconds // 60} 分钟至结束时间内签到')
        stamp = row['checked_at'] or now.isoformat(timespec='seconds')
        if not row['checked_at']:
            conn.execute('UPDATE attendance SET checked_at=? WHERE shift_id=? AND name=?', (stamp, shift_id, name))

        # Pair by the day's shift order (1st/2nd, 3rd/4th), not just this person's rows,
        # so someone assigned only to the 2nd and 3rd shifts is never chained.
        day_shifts = conn.execute(
            'SELECT id,day,start,end FROM shifts WHERE day=? ORDER BY start,id',
            (row['day'],)).fetchall()
        position = next((i for i, item in enumerate(day_shifts) if item['id'] == shift_id), -1)
        chained = []
        if position >= 0 and position % 2 == 0 and position + 1 < len(day_shifts):
            partner = day_shifts[position + 1]
            assigned = conn.execute(
                'SELECT checked_at FROM attendance WHERE shift_id=? AND name=?',
                (partner['id'], name)).fetchone()
            partner_start, partner_end = shift_bounds(partner)
            # The partner must belong to this person, be unchecked, and start when this one ends.
            if assigned and not assigned['checked_at'] and partner_start == end:
                conn.execute('UPDATE attendance SET checked_at=? WHERE shift_id=? AND name=?',
                             (stamp, partner['id'], name))
                chained.append(partner['id'])
        return stamp, chained
