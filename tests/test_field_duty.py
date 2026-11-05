from datetime import datetime

import unittest
import test_schedule
from server import field_duty, schedule_store


class TestFieldDuty(unittest.TestCase):
    setUp = test_schedule.ScheduleTest.setUp
    tearDown = test_schedule.ScheduleTest.tearDown

    def test_register_is_idempotent_per_month(self):
        first = field_duty.register('张三', month='2026-11')
        assert first['registered'] is True and first['created'] is True
        again = field_duty.register('张三', month='2026-11')
        assert again['created'] is False
        assert again['registered_at'] == first['registered_at']
        assert field_duty.member_status('张三', month='2026-11')['status'] == field_duty.PENDING
        assert field_duty.member_status('张三', month='2026-12')['registered'] is False

    def test_members_are_isolated(self):
        field_duty.register('张三', month='2026-11')
        assert field_duty.member_status('李四', month='2026-11')['status'] == field_duty.NONE
        assert field_duty.member_status('张三', month='2026-11')['status'] == field_duty.PENDING

    def test_overview_lists_registered_first_and_flags_the_rest(self):
        from server import member_store
        member_store.create_missing(['张三', '李四', '王五'])
        field_duty.register('王五', month='2026-11')
        field_duty.confirm('王五', month='2026-11')
        data = field_duty.overview(month='2026-11')
        names = [item['username'] for item in data['items']]
        assert names[0] == '王五'
        assert set(names) == {'张三', '李四', '王五'}
        assert data['registered'] == 1 and data['total'] == 3
        by_name = {item['username']: item for item in data['items']}
        assert by_name['王五']['registered'] is True
        assert by_name['李四']['registered'] is False

    def test_disabled_accounts_are_left_out(self):
        from server import member_store
        member_store.create_missing(['张三', '李四'])
        member_store.update('李四', active=False)
        data = field_duty.overview(month='2026-11')
        assert [item['username'] for item in data['items']] == ['张三']

    def test_registration_records_current_month_by_default(self):
        result = field_duty.register('张三')
        assert result['month'] == datetime.now(schedule_store.TZ).strftime('%Y-%m')
        assert field_duty.member_status('张三')['registered'] is True

    def test_admin_can_override_participation(self):
        from server import member_store
        member_store.create_missing(['张三', '李四'])
        # Marking someone as joined creates a timestamp the first time.
        joined = field_duty.set_participation('张三', True, month='2026-11')
        assert joined['registered'] and joined['manual'] and joined['registered_at']
        data = field_duty.overview(month='2026-11')
        by_name = {item['username']: item for item in data['items']}
        assert by_name['张三']['registered'] is True
        assert by_name['张三']['manual'] is True
        # Unmarking removes the record entirely.
        removed = field_duty.set_participation('张三', False, month='2026-11')
        assert removed['registered'] is False
        assert field_duty.overview(month='2026-11')['registered'] == 0
        # Re-marking keeps the original timestamp when one exists (self registration first).
        original = field_duty.register('李四', month='2026-11')
        again = field_duty.set_participation('李四', True, month='2026-11')
        assert again['registered_at'] == original['registered_at']
        assert again['manual'] is True

    def test_registration_moves_zero_to_one_only(self):
        first = field_duty.register('张三', month='2026-11')
        assert first['status'] == field_duty.PENDING
        assert first['label'] == '等待确认'
        # Registering again keeps it pending; it never auto-confirms.
        again = field_duty.register('张三', month='2026-11')
        assert again['status'] == field_duty.PENDING and again['created'] is False
        # Pending records are not counted by the admin board.
        assert field_duty.overview(month='2026-11')['registered'] == 0

    def test_pending_list_and_confirm_moves_one_to_two(self):
        from server import member_store
        member_store.create_missing(['张三', '李四'])
        field_duty.register('张三', month='2026-11')
        field_duty.register('李四', month='2026-11')
        field_duty.confirm('李四', month='2026-11')
        pending = field_duty.pending(month='2026-11')
        assert [item['username'] for item in pending['items']] == ['张三']
        assert pending['items'][0]['registered_at']
        result = field_duty.confirm('张三', month='2026-11')
        assert result['status'] == field_duty.CONFIRMED and result['label'] == '已确认'
        assert field_duty.pending(month='2026-11')['items'] == []
        assert field_duty.overview(month='2026-11')['registered'] == 2

    def test_confirm_requires_a_pending_registration(self):
        with self.assertRaises(LookupError):
            field_duty.confirm('从未登记', month='2026-11')

    def test_deleting_a_pending_record_resets_to_zero(self):
        field_duty.register('张三', month='2026-11')
        field_duty.set_participation('张三', False, month='2026-11')
        assert field_duty.member_status('张三', month='2026-11')['status'] == field_duty.NONE
        assert field_duty.pending(month='2026-11')['items'] == []
        # Registering again works after deletion.
        assert field_duty.register('张三', month='2026-11')['status'] == field_duty.PENDING

    def test_admin_override_marks_confirmed(self):
        field_duty.set_participation('王五', True, month='2026-11')
        assert field_duty.member_status('王五', month='2026-11')['status'] == field_duty.CONFIRMED
        assert field_duty.overview(month='2026-11')['registered'] == 1


class TestFieldDutyMonthNavigation(unittest.TestCase):
    setUp = test_schedule.ScheduleTest.setUp
    tearDown = test_schedule.ScheduleTest.tearDown

    def test_current_month_is_the_default_bound(self):
        from unittest.mock import patch
        from server import system_clock
        with patch.object(system_clock, 'now', return_value=datetime(2026, 11, 5, 12, 0,
                                                                     tzinfo=schedule_store.TZ)):
            field_duty.register('张三')
            data = field_duty.overview()
        assert data['month'] == '2026-11' and data['current'] == '2026-11'

    def test_records_extend_the_browsable_range(self):
        from unittest.mock import patch
        from server import system_clock
        field_duty.register('张三', month='2026-09')
        field_duty.confirm('张三', month='2026-09')
        field_duty.register('李四', month='2027-01')
        with patch.object(system_clock, 'now', return_value=datetime(2026, 11, 5, 12, 0,
                                                                     tzinfo=schedule_store.TZ)):
            october = field_duty.overview(month='2026-10')
        assert october['first'] == '2026-09' and october['last'] == '2027-01'
        assert october['previous'] == '2026-09'
        assert october['next'] == '2026-11'

    def test_arrows_disable_at_the_recorded_bounds(self):
        from unittest.mock import patch
        from server import system_clock
        field_duty.register('张三', month='2026-10')
        field_duty.register('李四', month='2026-12')
        with patch.object(system_clock, 'now', return_value=datetime(2026, 11, 5, 12, 0,
                                                                     tzinfo=schedule_store.TZ)):
            start = field_duty.overview(month='2026-10')
            end = field_duty.overview(month='2026-12')
        assert start['previous'] is None and start['next'] == '2026-11'
        assert end['next'] is None and end['previous'] == '2026-11'

    def test_current_month_is_always_reachable(self):
        from unittest.mock import patch
        from server import system_clock
        field_duty.register('张三', month='2026-06')
        field_duty.confirm('张三', month='2026-06')
        with patch.object(system_clock, 'now', return_value=datetime(2026, 11, 5, 12, 0,
                                                                     tzinfo=schedule_store.TZ)):
            data = field_duty.overview(month='2026-06')
            later = field_duty.overview(month='2026-11')
        assert data['first'] == '2026-06' and data['last'] == '2026-11'
        assert later['next'] is None
        assert later['previous'] == '2026-10'

    def test_month_stepping_crosses_year_boundaries(self):
        assert field_duty._shift_month('2026-01', -1) == '2025-12'
        assert field_duty._shift_month('2026-12', 1) == '2027-01'
        assert field_duty._shift_month('2026-06', -18) == '2024-12'
