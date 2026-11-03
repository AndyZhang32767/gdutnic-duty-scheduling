"""Monthly attendance statistics and weekly status for the admin overview."""
from datetime import date, datetime, timedelta

from server import db, duty_settings, schedule_store

STATUS_LABELS = {'normal': '正常', 'late': '迟到', 'absent': '旷班', 'pending': '待签到'}
# Statuses an administrator may set by hand from the overview card.
MANUAL_STATUSES = ('normal', 'late', 'absent')


def member_status(shift, member, now, rules):
    """Classify one attendance row from the shift start time.

    Thresholds are cumulative: anything after `absent_minutes` counts as absent,
    whether or not the person eventually checked in; `late_minutes` only covers
    the window between late and absent. An administrator's manual override wins.
    """
    override = str(member.get('status_override') or '')
    if override in MANUAL_STATUSES:
        return override
    start, end = schedule_store.shift_bounds(shift)
    late_at = start + timedelta(minutes=rules['late_minutes'])
    absent_at = start + timedelta(minutes=rules['absent_minutes'])
    checked = member.get('checked_at')
    if checked:
        try:
            at = datetime.fromisoformat(str(checked))
        except ValueError:
            return 'normal'
        if at.tzinfo is None:
            at = at.replace(tzinfo=schedule_store.TZ)
        if at >= absent_at:
            return 'absent'
        return 'late' if at > late_at else 'normal'
    if now >= absent_at:
        return 'absent'
    return 'pending'


def _attendance_by_shift(conn, rows):
    """One query for every shift's attendance instead of one per shift."""
    ids = [row['id'] for row in rows]
    grouped = {}
    if not ids:
        return grouped
    placeholders = ','.join('?' for _ in ids)
    for record in conn.execute(
            f'SELECT shift_id,name,checked_at,status_override FROM attendance WHERE shift_id IN ({placeholders})'
            ' ORDER BY shift_id,name', ids):
        grouped.setdefault(record['shift_id'], []).append(
            {'name': record['name'], 'checked_at': record['checked_at'],
             'status_override': record['status_override'] or ''})
    return grouped


def _shift_payload(conn, row, now, rules, attendance=None):
    members = [dict(m) for m in (attendance.get(row['id'], []) if attendance is not None else
               conn.execute('SELECT name,checked_at,status_override FROM attendance WHERE shift_id=? ORDER BY name',
                            (row['id'],)))]
    for member in members:
        member['status'] = member_status(row, member, now, rules)
    start, end = schedule_store.shift_bounds(row)
    if now < start:
        phase = 'future'
    elif now < end:
        phase = 'current'
    else:
        phase = 'past'
    item = dict(row)
    item.update(
        members=members,
        late=[m['name'] for m in members if m['status'] == 'late'],
        absent=[m['name'] for m in members if m['status'] == 'absent'],
        phase=phase,
    )
    return item


def _month_bounds(month):
    first = date.fromisoformat(str(month) + '-01')
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, following - timedelta(days=1)


def overview(month=None, now=None):
    now = now or datetime.now(schedule_store.TZ)
    rules = duty_settings.load()
    first, last = _month_bounds(month or now.strftime('%Y-%m'))
    week_start = now.date() - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)
    range_start = min(first, week_start)
    range_end = max(last, week_end)

    normal = late = absent = total = 0
    month_items = []
    all_items = []
    with db.read() as conn:
        schedule_store.init(conn)
        rows = conn.execute(
            'SELECT * FROM shifts WHERE day>=? AND day<=? ORDER BY day,start,id',
            (range_start.isoformat(), range_end.isoformat())).fetchall()
        attendance = _attendance_by_shift(conn, rows)
        for row in rows:
            item = _shift_payload(conn, row, now, rules, attendance)
            all_items.append(item)
            if first.isoformat() <= item['day'] <= last.isoformat():
                month_items.append(item)
                # Only shifts that have already started count towards the month's rate.
                if schedule_store.shift_bounds(row)[0] <= now:
                    for member in item['members']:
                        total += 1
                        if member['status'] == 'normal':
                            normal += 1
                        elif member['status'] == 'late':
                            late += 1
                        elif member['status'] == 'absent':
                            absent += 1
        timeline = []
        today = now.date().isoformat()
        previous = (now.date() - timedelta(days=1)).isoformat()
        timeline_rows = conn.execute(
            "SELECT * FROM shifts WHERE day=? OR (day=? AND end < start AND end > '00:00')"
            " ORDER BY day,start,id", (today, previous)).fetchall()
        timeline_attendance = _attendance_by_shift(conn, timeline_rows)
        for row in timeline_rows:
            timeline.append(_shift_payload(conn, row, now, rules, timeline_attendance))

    days = []
    for offset in range(7):
        current = week_start + timedelta(days=offset)
        days.append({
            'day': current.isoformat(),
            'weekday': current.weekday(),
            'shifts': _range_items(all_items, current),
        })
    return {
        'month': first.strftime('%Y-%m'),
        'today': now.date().isoformat(),
        'rules': rules,
        'stats': {
            'normal': normal,
            'total': total,
            'late': late,
            'absent': absent,
            'rate': round(normal / total * 100, 1) if total else None,
        },
        'timeline': timeline,
        'week': {'start': week_start.isoformat(), 'end': week_end.isoformat(), 'days': days},
    }


def _range_items(items, day):
    return [item for item in items if item['day'] == day.isoformat()]


def set_member_status(shift_id, name, status):
    """Administrator override for one person's attendance status."""
    if status not in MANUAL_STATUSES:
        raise ValueError('考勤状态只能设为准时、迟到或旷班')
    with db.write() as conn:
        row = conn.execute('SELECT name FROM attendance WHERE shift_id=? AND name=?',
                           (shift_id, name)).fetchone()
        if not row:
            raise LookupError('未找到该班次或排班人员')
        conn.execute('UPDATE attendance SET status_override=? WHERE shift_id=? AND name=?',
                     (status, shift_id, name))
    return {'shift_id': shift_id, 'name': name, 'status': status}
