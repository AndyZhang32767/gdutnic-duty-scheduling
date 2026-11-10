"""Security boundary checks using real login sessions and a temporary SQLite DB."""
import re
from unittest.mock import patch

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from test_permissions import PermissionFixture
from server import app as api, admin_store, db, field_duty, member_store, permissions, schedule_store, security, weekly_store


class SecurityBoundariesTest(PermissionFixture):
    def setUp(self):
        super().setUp()
        self.patches = [patch.object(api, 'ADMIN_LIMITER', security.AttemptLimiter()),
                        patch.object(api, 'ACCOUNT_LIMITER', security.AttemptLimiter()),
                        patch.object(weekly_store, 'SEED', db.DATA / 'weekly_roster.json')]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        member_store.create('alice', 'password123')
        member_store.create('bob', 'password123')
        admin_store.remember_setup('alice')

    def login(self, name='alice', admin=False):
        client = TestClient(api.app)
        if admin:
            client.get('/' + admin_store.path())
        response = client.post('/api/admin/login' if admin else '/api/member/login',
                               json={'username': name, 'password': 'password123'})
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def test_all_privileged_admin_routes_reject_anonymous_and_member_sessions(self):
        clients = [TestClient(api.app), self.login()]
        exempt = {'/api/admin/status', '/api/admin/login', '/api/admin/register', '/api/admin/logout'}
        checked = 0
        for route in api.app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith('/api/admin/') or route.path in exempt:
                continue
            path = re.sub(r'\{([^}]+)\}', lambda m: '1' if m[1] in ('shift_id', 'swap_id') else 'probe', route.path)
            for method in route.methods:
                for client in clients:
                    response = client.request(method, path, params={'day': '2026-11-02'}, json={})
                    self.assertEqual(response.status_code, 401, (method, path, response.text))
                checked += 1
        self.assertGreaterEqual(checked, 65)
        print(f'Validated {checked} privileged admin operations for anonymous and member sessions')

    def test_member_cannot_gain_admin_by_visiting_secret_slug(self):
        client = self.login()
        client.get('/' + admin_store.path())
        response = client.post('/api/admin/login', json={'username': 'alice', 'password': 'password123'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get('/api/admin/data/tables').status_code, 401)

    def test_admin_password_reset_revokes_old_admin_session(self):
        permissions.set_permissions('alice', ['logs'])
        client = self.login(admin=True)
        self.assertEqual(client.get('/api/admin/logs').status_code, 200)
        member_store.set_password('alice', 'new-password-456')
        self.assertEqual(client.get('/api/admin/logs').status_code, 401)

    def test_field_confirmation_permission_and_revocation(self):
        client = self.login()
        field_duty.register('bob')
        self.assertEqual(client.post('/api/member/field-duty/pending/bob').status_code, 200)
        self.assertEqual(field_duty.member_status('bob')['status'], field_duty.CONFIRMED)
        permissions.set_permissions('alice', ['duty', 'member_field'])
        for method in ('POST', 'DELETE'):
            self.assertEqual(client.request(method, '/api/member/field-duty/pending/bob').status_code, 403)
        self.assertEqual(field_duty.member_status('bob')['status'], field_duty.CONFIRMED)

    def test_pending_reject_cannot_delete_confirmed_record(self):
        client = self.login()
        field_duty.register('bob')
        field_duty.confirm('bob')
        response = client.delete('/api/member/field-duty/pending/bob')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(field_duty.member_status('bob')['status'], field_duty.CONFIRMED)

    def test_pending_reject_removes_only_pending_record(self):
        client = self.login()
        field_duty.register('bob')
        self.assertEqual(client.delete('/api/member/field-duty/pending/bob').status_code, 200)
        self.assertEqual(field_duty.member_status('bob')['status'], field_duty.NONE)

    def test_check_in_cannot_override_session_owner_with_body(self):
        client = self.login()
        sid = schedule_store.save(dict(day='2026-11-02', start='09:00', end='12:00', members=['bob']))
        with patch.object(schedule_store.system_clock, 'now', return_value=self.now):
            response = client.post(f'/api/schedules/{sid}/check-in', json={'username': 'bob', 'name': 'bob'})
        self.assertEqual(response.status_code, 404)
        with db.read() as conn:
            self.assertIsNone(conn.execute('SELECT checked_at FROM attendance WHERE shift_id=? AND name=?', (sid, 'bob')).fetchone()['checked_at'])

    def test_password_requires_old_password_and_uses_session_owner(self):
        client = self.login()
        old_session = self.login()
        for old in ('', 'wrong-password'):
            response = client.post('/api/member/password', json={'username': 'bob', 'old_password': old, 'new_password': 'new-password-456'})
            self.assertEqual(response.status_code, 400)
            self.assertTrue(member_store.verify('alice', 'password123'))
        response = client.post('/api/member/password', json={'username': 'bob', 'old_password': 'password123', 'new_password': 'new-password-456'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(member_store.verify('alice', 'new-password-456'))
        self.assertTrue(member_store.verify('bob', 'password123'))
        self.assertEqual(old_session.get('/api/member/field-duty').status_code, 401)
        self.assertEqual(client.get('/api/member/field-duty').status_code, 200)

    def test_data_console_masks_model_and_smtp_credentials(self):
        permissions.set_permissions('alice', ['data'])
        client = self.login(admin=True)
        with db.write() as conn:
            db.set_setting(conn, 'model', {'openai_key': 'MODEL_TEST_SECRET'})
            db.set_setting(conn, 'smtp', {'password': 'SMTP_TEST_SECRET'})
        response = client.get('/api/admin/data/tables/settings')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('MODEL_TEST_SECRET', response.text)
        self.assertNotIn('SMTP_TEST_SECRET', response.text)

    def test_limited_admin_cannot_access_other_admin_operations(self):
        permissions.set_permissions('alice', ['logs'])
        client = self.login(admin=True)
        exempt = {'/api/admin/status', '/api/admin/login', '/api/admin/register', '/api/admin/logout', '/api/admin/logs'}
        for route in api.app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith('/api/admin/') or route.path in exempt:
                continue
            path = re.sub(r'\{([^}]+)\}', lambda m: '1' if m[1] in ('shift_id', 'swap_id') else 'probe', route.path)
            for method in route.methods:
                response = client.request(method, path, json={})
                self.assertEqual(response.status_code, 403, (method, path, response.text))

    def test_member_ssrf_cannot_override_configured_destination(self):
        client = self.login()
        with patch.object(api.admin_store, 'mcp_url', return_value=''), patch.object(api, 'OutlineMcpClient') as upstream:
            response = client.post('/api/mcp/connect', json={'mcp_url': 'http://127.0.0.1:10000', 'mcp_api_key': 'x'})
            self.assertEqual(response.status_code, 400)
            upstream.assert_not_called()
        with patch.object(api.admin_store, 'mcp_url', return_value='https://wiki.example/mcp'), patch.object(api, 'OutlineMcpClient') as upstream:
            upstream.return_value.__aenter__.side_effect = RuntimeError('mock connection failure')
            response = client.post('/api/mcp/connect', json={'mcp_url': 'http://127.0.0.1:10000', 'mcp_api_key': 'x'})
            self.assertEqual(response.status_code, 502)
            upstream.assert_called_once_with('https://wiki.example/mcp', 'x')

    def test_special_only_admin_cannot_modify_regular_shift(self):
        permissions.set_permissions('alice', ['special'])
        client = self.login(admin=True)
        body = dict(day='2026-11-02', start='09:00', end='12:00', members=['bob'])
        sid = schedule_store.save(body)
        response = client.put(f'/api/admin/special-schedules/{sid}', json={**body, 'members': ['alice']})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(client.delete(f'/api/admin/special-schedules/{sid}').status_code, 404)
        with db.read() as conn:
            self.assertEqual([row['name'] for row in conn.execute('SELECT name FROM attendance WHERE shift_id=?', (sid,))], ['bob'])

    def test_secret_settings_cannot_be_overwritten_through_data_console(self):
        permissions.set_permissions('alice', ['data'])
        client = self.login(admin=True)
        with db.write() as conn:
            db.set_setting(conn, 'smtp', {'password': 'SMTP_TEST_SECRET'})
        response = client.put('/api/admin/data/tables/settings', json={'keys': {'key': 'smtp'}, 'values': {'value': '{}'}})
        self.assertEqual(response.status_code, 400)
        with db.read() as conn:
            self.assertEqual(db.get_setting(conn, 'smtp'), {'password': 'SMTP_TEST_SECRET'})

    def test_roster_validates_untrusted_json_before_creating_accounts(self):
        permissions.set_permissions('alice', ['weekly'])
        client = self.login(admin=True)
        roster = weekly_store.empty_roster()
        roster['slots'][0]['days'][0] = [{'__class__': 'malicious'}]
        response = client.put('/api/admin/weekly-roster', json=roster)
        self.assertEqual(response.status_code, 400)
        self.assertEqual({row['username'] for row in member_store.list_accounts()}, {'alice', 'bob'})
        with db.read() as conn:
            self.assertIsNone(db.get_setting(conn, weekly_store.KEY))

    def test_roster_sql_and_html_payloads_are_stored_as_plain_names(self):
        permissions.set_permissions('alice', ['weekly'])
        client = self.login(admin=True)
        roster = weekly_store.empty_roster()
        names = ["x'); DROP TABLE member_accounts;--", '<img onerror=alert(1)>', '__proto__']
        roster['slots'][0]['days'][0] = names
        response = client.put('/api/admin/weekly-roster', json=roster)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(weekly_store.load()['slots'][0]['days'][0], names)
        self.assertTrue(member_store.verify('bob', 'password123'))
