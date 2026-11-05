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


class TestOverviewWeekNavigation(unittest.TestCase):
    setUp = test_schedule.ScheduleTest.setUp
    tearDown = test_schedule.ScheduleTest.tearDown

    def make(self, day, start='09:00', end='10:00', names=('甲',)):
        return schedule_store.save(dict(day=day, start=start, end=end, members=list(names)))

    def test_current_week_is_the_anchor_by_default(self):
        self.make('2026-11-04')
        now = datetime(2026, 11, 5, 12, 0, tzinfo=schedule_store.TZ)
        week = overview.overview('2026-11', now=now)['week']
        assert week['start'] == '2026-11-02' and week['end'] == '2026-11-08'
        assert week['current'] == '2026-11-02'

    def test_previous_and_next_follow_the_requested_week(self):
        self.make('2026-10-21')
        self.make('2026-11-04')
        self.make('2026-11-18')
        now = datetime(2026, 11, 5, 12, 0, tzinfo=schedule_store.TZ)
        back = overview.overview('2026-11', now=now, week='2026-10-21')['week']
        assert back['start'] == '2026-10-19'
        assert back['previous'] is None                    # earliest recorded week
        assert back['next'] == '2026-10-26'
        assert [s['day'] for d in back['days'] for s in d['shifts']] == ['2026-10-21']
        # Gap weeks are still reachable, up to the newest recorded week.
        middle = overview.overview('2026-11', now=now, week='2026-10-28')['week']
        assert middle['previous'] == '2026-10-19' and middle['next'] == '2026-11-02'

    def test_any_day_in_the_week_anchors_the_same_board(self):
        self.make('2026-11-04')
        now = datetime(2026, 11, 5, 12, 0, tzinfo=schedule_store.TZ)
        for anchor in ('2026-11-02', '2026-11-04', '2026-11-08'):
            week = overview.overview('2026-11', now=now, week=anchor)['week']
            assert week['start'] == '2026-11-02', anchor
            # The only shift is this week's, so it is both bound and the current week.
            assert week['previous'] is None and week['next'] is None, anchor

    def test_arrows_disable_at_the_recorded_bounds(self):
        first = self.make('2026-11-04')
        last = self.make('2026-11-18')
        now = datetime(2026, 11, 5, 12, 0, tzinfo=schedule_store.TZ)
        earliest = overview.overview('2026-11', now=now, week='2026-11-04')['week']
        assert earliest['first'] == '2026-11-02'
        assert earliest['previous'] is None and earliest['next'] == '2026-11-09'
        latest = overview.overview('2026-11', now=now, week='2026-11-18')['week']
        assert latest['last'] == '2026-11-16'
        assert latest['next'] is None and latest['previous'] == '2026-11-09'
        assert first and last

    def test_bounds_always_include_the_current_week(self):
        # Every shift is in the past, yet this week stays reachable.
        self.make('2026-10-07')
        now = datetime(2026, 11, 5, 12, 0, tzinfo=schedule_store.TZ)
        week = overview.overview('2026-11', now=now)['week']
        assert week['last'] == '2026-11-02'
        assert week['next'] is None
        assert week['previous'] == '2026-10-26'

    def test_empty_schedule_disables_both_arrows(self):
        now = datetime(2026, 11, 5, 12, 0, tzinfo=schedule_store.TZ)
        week = overview.overview('2026-11', now=now)['week']
        assert week['previous'] is None and week['next'] is None
        assert week['first'] == week['last'] == '2026-11-02'

    def test_invalid_week_is_rejected(self):
        with self.assertRaises(ValueError):
            overview.overview('2026-11', now=datetime(2026, 11, 5, 12, 0, tzinfo=schedule_store.TZ),
                              week='not-a-day')
