from datetime import datetime
from unittest.mock import patch

import unittest
import test_schedule
from server import duty_settings, overview, schedule_store


class TestOverview(unittest.TestCase):
    setUp = test_schedule.ScheduleTest.setUp
    tearDown = test_schedule.ScheduleTest.tearDown

    def make(self, day, start, end, names):
        return schedule_store.save(dict(day=day, start=start, end=end, members=names))

    def stamp(self, sid, name, at):
        with patch.object(schedule_store, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = at
            schedule_store.check_in(sid, name)

    def test_normal_late_absent_and_rate(self):
        now = datetime(2026, 11, 3, 12, 30, tzinfo=schedule_store.TZ)
        on_time = self.make('2026-11-02', '08:30', '10:00', ['甲'])
        late = self.make('2026-11-02', '10:15', '12:00', ['乙', '丙'])
        missed = self.make('2026-11-03', '08:30', '10:00', ['丁'])
        self.stamp(on_time, '甲', datetime(2026, 11, 2, 8, 25, tzinfo=schedule_store.TZ))
        self.stamp(late, '乙', datetime(2026, 11, 2, 10, 40, tzinfo=schedule_store.TZ))
        self.stamp(late, '丙', datetime(2026, 11, 2, 10, 20, tzinfo=schedule_store.TZ))
        data = overview.overview('2026-11', now=now)
        assert data['stats'] == {'normal': 2, 'total': 4, 'late': 1, 'absent': 1, 'rate': 50.0}
        week_shifts = [s for d in data['week']['days'] for s in d['shifts']]
        past = [s for s in week_shifts if s['day'] == '2026-11-02' and s['start'] == '10:15'][0]
        assert past['late'] == ['乙'] and past['absent'] == []
        missed_day = [s for s in week_shifts if s['day'] == '2026-11-03'][0]
        assert missed_day['absent'] == ['丁']
        assert missed_day['phase'] == 'past'

    def test_future_shift_is_pending_and_not_counted(self):
        now = datetime(2026, 11, 3, 8, 0, tzinfo=schedule_store.TZ)
        self.make('2026-11-05', '08:30', '10:00', ['甲'])
        data = overview.overview('2026-11', now=now)
        assert data['stats']['total'] == 0 and data['stats']['rate'] is None
        column = data['week']['days'][4]
        assert column['day'] == '2026-11-06' or column['day'] == '2026-11-05'
        future = [s for d in data['week']['days'] for s in d['shifts']][0]
        assert future['phase'] == 'future'
        assert [m['status'] for m in future['members']] == ['pending']

    def test_week_board_covers_monday_to_sunday_across_months(self):
        now = datetime(2026, 11, 3, 9, 0, tzinfo=schedule_store.TZ)
        self.make('2026-11-01', '08:30', '10:00', ['甲'])
        data = overview.overview('2026-12', now=now)
        assert data['week']['start'] == '2026-11-02'
        assert data['week']['end'] == '2026-11-08'
        assert [d['day'] for d in data['week']['days']][0] == '2026-11-02'
        assert data['month'] == '2026-12'

    def test_month_boundaries_include_last_day(self):
        now = datetime(2026, 11, 30, 23, 0, tzinfo=schedule_store.TZ)
        self.make('2026-11-30', '08:30', '10:00', ['甲'])
        self.make('2026-12-01', '08:30', '10:00', ['乙'])
        data = overview.overview('2026-11', now=now)
        assert [s['day'] for s in data['timeline'] if s['day'].startswith('2026-11-3')] == ['2026-11-30']
        assert data['stats']['total'] == 1

    def test_check_in_after_absence_threshold_is_absent_not_late(self):
        # Shift starts 09:00; late >15 minutes, absent >30 minutes, both from 09:00.
        duty_settings.save({'early_minutes': 10, 'late_minutes': 15, 'absent_minutes': 30})
        sid = self.make('2026-11-02', '09:00', '11:00', ['早到', '迟到', '旷到'])
        self.stamp(sid, '早到', datetime(2026, 11, 2, 9, 10, tzinfo=schedule_store.TZ))
        self.stamp(sid, '迟到', datetime(2026, 11, 2, 9, 20, tzinfo=schedule_store.TZ))
        self.stamp(sid, '旷到', datetime(2026, 11, 2, 9, 40, tzinfo=schedule_store.TZ))
        data = overview.overview('2026-11', now=datetime(2026, 11, 2, 12, 0, tzinfo=schedule_store.TZ))
        shift = [s for d in data['week']['days'] for s in d['shifts'] if s['start'] == '09:00'][0]
        statuses = {m['name']: m['status'] for m in shift['members']}
        assert statuses == {'早到': 'normal', '迟到': 'late', '旷到': 'absent'}
        assert shift['late'] == ['迟到']
        assert shift['absent'] == ['旷到']
        assert data['stats'] == {'normal': 1, 'total': 3, 'late': 1, 'absent': 1, 'rate': 33.3}

    def test_absence_window_uses_shift_start_even_for_overnight(self):
        duty_settings.save({'early_minutes': 10, 'late_minutes': 10, 'absent_minutes': 20})
        sid = self.make('2026-11-03', '23:00', '01:00', ['夜班'])
        self.stamp(sid, '夜班', datetime(2026, 11, 3, 23, 35, tzinfo=schedule_store.TZ))
        data = overview.overview('2026-11', now=datetime(2026, 11, 4, 0, 10, tzinfo=schedule_store.TZ))
        shift = [s for s in data['timeline'] if s['id'] == sid][0]
        assert shift['members'][0]['status'] == 'absent'

    def test_rules_change_shift_classification(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=schedule_store.TZ)
        sid = self.make('2026-11-02', '09:00', '10:00', ['甲'])
        self.stamp(sid, '甲', datetime(2026, 11, 2, 9, 20, tzinfo=schedule_store.TZ))
        duty_settings.save({'late_minutes': 30, 'absent_minutes': 60})
        data = overview.overview('2026-11', now=now)
        assert data['stats']['late'] == 0 and data['stats']['normal'] == 1

    def test_manual_status_override_wins(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=schedule_store.TZ)
        sid = self.make('2026-11-02', '09:00', '10:00', ['甲'])
        self.stamp(sid, '甲', datetime(2026, 11, 2, 9, 5, tzinfo=schedule_store.TZ))
        data = overview.overview('2026-11', now=now)
        shift = [s for s in data['timeline'] if s['id'] == sid][0]
        assert shift['members'][0]['status'] == 'normal'
        overview.set_member_status(sid, '甲', 'late')
        data = overview.overview('2026-11', now=now)
        shift = [s for s in data['timeline'] if s['id'] == sid][0]
        assert shift['members'][0]['status'] == 'late'
        assert data['stats']['late'] == 1

    def test_manual_status_rejects_unknown_values(self):
        sid = self.make('2026-11-02', '09:00', '10:00', ['甲'])
        with self.assertRaises(ValueError):
            overview.set_member_status(sid, '甲', 'pending')
        with self.assertRaises(LookupError):
            overview.set_member_status(sid, '不存在', 'late')
