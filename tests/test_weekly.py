from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch

import unittest
import test_schedule
from server import db, schedule_store, weekly_store


class WeeklyTest(unittest.TestCase):
    setUp = test_schedule.ScheduleTest.setUp
    tearDown = test_schedule.ScheduleTest.tearDown
    def roster(self):
        return dict(location='网络中心', needs_review=False, slots=[
            dict(start=start, end=end, days=[[f'人员{i}'] for _ in range(7)])
            for i, (start, end) in enumerate([('08:00','10:00'),('10:00','12:00'),('14:00','16:00'),('16:00','18:00')])
        ])

    def test_week_publication_repeat_and_attendance(self):
        weekly_store.save(self.roster())
        self.assertEqual(weekly_store.publish('2026-11-02'), dict(created=28, skipped=0))
        shifts = schedule_store.list_day('2026-11-02')
        with patch.object(schedule_store, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now.replace(hour=8)
            stamp = schedule_store.check_in(shifts[0]['id'], '人员0')
        self.assertEqual(weekly_store.publish('2026-11-02'), dict(created=0, skipped=28))
        self.assertEqual(schedule_store.list_day('2026-11-02')[0]['members'][0]['checked_at'], stamp)
        changed = self.roster()
        changed['slots'][0]['days'][0] = ['新人员']
        weekly_store.save(changed)
        weekly_store.publish('2026-11-02')
        self.assertEqual(schedule_store.list_day('2026-11-02')[0]['members'][0]['name'], '人员0')
        self.assertEqual(weekly_store.publish('2026-11-09')['created'], 28)
        self.assertEqual(schedule_store.list_day('2026-11-09')[0]['members'][0]['name'], '新人员')

    def test_missing_times_review_and_monday(self):
        original = self.roster()
        for change in ('review', 'time', 'overlap'):
            roster = deepcopy(original)
            if change == 'review': roster['needs_review'] = True
            if change == 'time': roster['slots'][0]['start'] = roster['slots'][0]['end'] = ''
            if change == 'overlap': roster['slots'][1]['start'] = '09:00'
            weekly_store.save(roster)
            with self.assertRaises(ValueError):
                weekly_store.publish('2026-11-02')
            self.assertEqual(schedule_store.list_day('2026-11-02'), [])
        weekly_store.save(original)
        with self.assertRaises(ValueError):
            weekly_store.publish('2026-11-03')

    def test_manual_conflict_and_blank_cell(self):
        roster = self.roster()
        roster['slots'][3]['days'][6] = []
        weekly_store.save(roster)
        sid = schedule_store.save(self.body)
        result = weekly_store.publish('2026-11-02')
        self.assertEqual(result, dict(created=25, skipped=2))
        self.assertEqual(len(schedule_store.list_day('2026-11-02')), 3)
        self.assertEqual(len(schedule_store.list_day('2026-11-08')), 3)
        self.assertTrue(any(s['id'] == sid for s in schedule_store.list_day('2026-11-02')))

    def test_failed_publication_rolls_back(self):
        weekly_store.save(self.roster())
        with db.write() as conn:
            schedule_store.init(conn)
            conn.execute("CREATE TRIGGER reject_wednesday BEFORE INSERT ON shifts WHEN NEW.day='2026-11-04' BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            weekly_store.publish('2026-11-02')
        self.assertEqual(schedule_store.list_day('2026-11-02'), [])

    def test_publish_until_matches_weekdays_and_includes_end(self):
        roster = self.roster()
        roster.pop('location')
        roster['slots'][0]['days'] = [[f'星期{i}'] for i in range(7)]
        weekly_store.save(roster)
        with patch.object(weekly_store, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now + timedelta(days=2)
            self.assertEqual(weekly_store.publish_until('2026-11-10')['created'], 28)
            self.assertEqual(weekly_store.publish_until('2026-11-10')['created'], 0)
            with self.assertRaises(ValueError): weekly_store.publish_until('2026-11-03')
        self.assertEqual(schedule_store.list_day('2026-11-03'), [])
        self.assertEqual(schedule_store.list_day('2026-11-04')[0]['members'][0]['name'], '星期2')
        self.assertEqual(schedule_store.list_day('2026-11-10')[0]['members'][0]['name'], '星期1')
        self.assertEqual(schedule_store.list_day('2026-11-11'), [])

    def test_clear_all_preserves_template_and_allows_regeneration(self):
        weekly_store.save(self.roster())
        weekly_store.publish('2026-11-02')
        sid = schedule_store.list_day('2026-11-02')[0]['id']
        with patch.object(schedule_store, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now.replace(hour=8)
            schedule_store.check_in(sid, '人员0')
        self.assertEqual(schedule_store.clear_all(), {'deleted': 28})
        with db.read() as conn:
            for table in ('shifts', 'attendance', 'weekly_instances'):
                self.assertEqual(conn.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n'], 0)
        self.assertEqual(weekly_store.load()['slots'], weekly_store.validate(self.roster())['slots'])
        self.assertEqual(weekly_store.publish('2026-11-02')['created'], 28)

    def test_seed_draft_is_available_without_saved_settings(self):
        roster = weekly_store.load()
        self.assertTrue(roster['needs_review'])
        self.assertEqual(len(roster['slots']), 4)
        self.assertTrue(all(len(s['days']) == 7 for s in roster['slots']))

    def test_overnight_week_and_conflict_across_date_boundary(self):
        roster=self.roster()
        roster['slots'][-1].update(start='22:00',end='02:00')
        weekly_store.save(roster)
        schedule_store.save({**self.body, 'day':'2026-11-03','start':'01:00','end':'03:00'})
        self.assertEqual(weekly_store.publish('2026-11-02'),dict(created=27,skipped=1))
        self.assertEqual(len(schedule_store.list_day('2026-11-09')),1)
        overnight=next(s for s in schedule_store.list_day('2026-11-09') if s['start']=='22:00')
        self.assertEqual(overnight['day'],'2026-11-08')
        roster['slots'][-1]['end']='10:00'
        weekly_store.save(roster)
        with self.assertRaises(ValueError): weekly_store.publish('2026-11-09')
