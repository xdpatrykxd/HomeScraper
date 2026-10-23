import base64
import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings, Filters
from app.database import Database
from app.gateway import WhatsAppGateway, GatewayError, RejectedSend, AmbiguousSend, chat_id, parse_groups
from app.main import scan
from app.notifier import Notifier, whatsapp
from scripts.setup_env import setup


def settings():
    return SimpleNamespace(gateway_url='http://gateway:3000', gateway_key='private-key',
        gateway_session='default', gateway_timeout=60,
        recipients=['+32470111111', 'whatsapp:+32470222222'], concurrency=2,
        filters=lambda: Filters(sources={'immoweb': True}))


class SettingsTests(unittest.TestCase):
    def test_config_without_old_provider_credentials(self):
        with patch.dict(os.environ, {'WAHA_API_KEY': 'a-key', 'WHATSAPP_RECIPIENT_1': '+32470111111'}, clear=True), patch('app.config.load_dotenv'):
            s = Settings()
            s.validate_whatsapp()
            self.assertEqual(s.gateway_url, 'http://127.0.0.1:3010')
            self.assertEqual(s.gateway_session, 'default')

    def test_invalid_gateway_settings(self):
        for key, value in [('WAHA_API_KEY', ''), ('WAHA_API_KEY', 'sha512:hash'),
                           ('WHATSAPP_GATEWAY_URL', 'file:///tmp/gateway'),
                           ('WHATSAPP_GATEWAY_URL', 'http://user:pass@gateway'),
                           ('WHATSAPP_SESSION', '../other'), ('WHATSAPP_GATEWAY_TIMEOUT_SECONDS', 'nan')]:
            with self.subTest(key=key), patch.dict(os.environ, {'WAHA_API_KEY': 'a-key', key: value}, clear=True), patch('app.config.load_dotenv'):
                with self.assertRaises(ValueError):
                    Settings().validate_gateway()

    def test_legacy_recipient_identity_is_preserved(self):
        self.assertEqual(whatsapp('+32470111111'), 'whatsapp:+32470111111')
        self.assertEqual(chat_id('whatsapp:+32470111111'), '32470111111@c.us')
        for value in ['32470111111', '+0', 'http://example.com']:
            with self.assertRaises(ValueError):
                chat_id(value)

    def test_group_recipient_identity_and_validation(self):
        for group in ['120363123456789@g.us', '32470111111-1650123456@g.us']:
            self.assertEqual(whatsapp(group), group)
            self.assertEqual(whatsapp('whatsapp:' + group), group)
            self.assertEqual(chat_id(group), group)
        for invalid in ['Family chat', 'https://chat.whatsapp.com/Invite', '120363123456789',
                        '120363123456789@g.us.evil', '123-456-789@g.us']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                whatsapp(invalid)

    def test_group_only_and_mixed_configuration(self):
        group = '120363123456789@g.us'
        with patch.dict(os.environ, {'WAHA_API_KEY': 'key', 'WHATSAPP_GROUP_IDS': group}, clear=True), patch('app.config.load_dotenv'):
            s = Settings()
            s.validate_whatsapp()
            self.assertEqual(s.recipients, [group])
        with patch.dict(os.environ, {'WAHA_API_KEY': 'key', 'WHATSAPP_GROUP_IDS': group,
                       'WHATSAPP_RECIPIENTS': f'+32470111111,{group}',
                       'WHATSAPP_RECIPIENT_1': 'whatsapp:+32470111111'}, clear=True), patch('app.config.load_dotenv'):
            s = Settings()
            s.validate_whatsapp()
            self.assertEqual(len(set(whatsapp(r) for r in s.recipients)), 2)
        with patch.dict(os.environ, {'WAHA_API_KEY': 'key', 'WHATSAPP_GROUP_IDS': '+32470111111'}, clear=True), patch('app.config.load_dotenv'):
            with self.assertRaisesRegex(ValueError, 'WHATSAPP_GROUP_IDS'):
                Settings().validate_whatsapp()

    def test_engine_specific_group_responses(self):
        group = '120363123456789@g.us'
        examples = [[{'JID': group, 'Name': 'Home search', 'Participants': [{'secret': 'ignored'}]}],
                    [{'id': {'_serialized': group}, 'name': 'Home search'}],
                    {group: {'subject': 'Home search'}}]
        for response in examples:
            self.assertEqual(parse_groups(response), [{'id': group, 'name': 'Home search'}])
        self.assertEqual(parse_groups([]), [])
        self.assertEqual(parse_groups({}), [])
        for invalid in [None, [{'JID': 'not-a-group'}], ['not-an-object'], [{'JID': group, 'Name': 42}]]:
            with self.assertRaises(GatewayError):
                parse_groups(invalid)

    def test_setup_preserves_existing_key_and_recipients(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text('TWILIO_AUTH_TOKEN=old-secret\nWHATSAPP_RECIPIENT_1=+32470111111\nCHECK_INTERVAL_MINUTES=3\n')
            with contextlib.redirect_stdout(io.StringIO()):
                setup(path)
            first = path.read_text()
            self.assertNotIn('TWILIO_AUTH_TOKEN', first)
            self.assertIn('WHATSAPP_RECIPIENT_1=+32470111111', first)
            self.assertIn('CHECK_INTERVAL_MINUTES=3', first)
            with contextlib.redirect_stdout(io.StringIO()):
                setup(path)
            self.assertEqual(path.read_text(), first)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_discovery_pagination(self):
        offsets = []
        def handler(request):
            if request.url.path == '/api/sessions/default':
                return httpx.Response(200, json={'status': 'WORKING'})
            self.assertEqual(request.url.path, '/api/default/groups')
            self.assertEqual(request.headers['X-Api-Key'], 'private-key')
            self.assertEqual(request.url.params['exclude'], 'participants')
            offset = int(request.url.params['offset'])
            offsets.append(offset)
            rows = [{'JID': '120363111@g.us', 'Name': 'First'}, {'JID': '120363222@g.us', 'Name': 'Second'}] if offset == 0 else [{'JID': '120363333@g.us', 'Name': 'Third'}]
            return httpx.Response(200, json=rows)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            groups = await WhatsAppGateway(settings(), client).list_groups(page_size=2)
        self.assertEqual(offsets, [0, 2])
        self.assertEqual([g['name'] for g in groups], ['First', 'Second', 'Third'])

    async def test_group_discovery_repeated_page_and_malformed_response(self):
        def handler(request):
            if request.url.path == '/api/sessions/default':
                return httpx.Response(200, json={'status': 'WORKING'})
            return httpx.Response(200, json=[{'JID': '120363111@g.us', 'Name': 'First'}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(GatewayError, 'repeated'):
                await WhatsAppGateway(settings(), client).list_groups(page_size=1)
        def invalid_handler(request):
            return httpx.Response(200, json={'status': 'WORKING'}) if request.url.path == '/api/sessions/default' else httpx.Response(200, text='not-json')
        async with httpx.AsyncClient(transport=httpx.MockTransport(invalid_handler)) as client:
            with self.assertRaisesRegex(GatewayError, 'JSON'):
                await WhatsAppGateway(settings(), client).list_groups()

    async def test_group_delivery_and_duplicate_protection(self):
        from app.models import Property
        group = '120363123456789@g.us'
        s = settings()
        s.recipients = ['+32470111111', group, 'whatsapp:' + group]
        class FakeScraper:
            def __init__(self, *args): pass
            async def search(self, config):
                return [Property('immoweb', '1', 'https://example.com/1')]
        posts = []
        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'status': 'WORKING'})
            destination = json.loads(request.content)['chatId']
            posts.append(destination)
            if len(posts) == 2:
                return httpx.Response(429)
            return httpx.Response(201, json={'id': f'true_{destination}_MESSAGE'})
        db = Database(':memory:')
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch.dict('app.main.SCRAPERS', {'immoweb': FakeScraper}):
                    self.assertFalse(await scan(s, client, db, False))
                    self.assertTrue(await scan(s, client, db, False))
                    self.assertTrue(await scan(s, client, db, False))
            self.assertEqual(posts, ['32470111111@c.us', group, group])
            self.assertEqual(db.conn.execute('SELECT recipient,state FROM deliveries ORDER BY recipient').fetchall(),
                             [(group, 'accepted'), ('whatsapp:+32470111111', 'accepted')])
        finally:
            db.close()

    async def test_status_and_readiness(self):
        for state in ['WORKING', 'SCAN_QR_CODE', 'STOPPED', None]:
            def handler(request):
                return httpx.Response(404) if state is None else httpx.Response(200, json={'status': state})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                gateway = WhatsAppGateway(settings(), client)
                self.assertEqual(await gateway.status(), state)
                if state == 'WORKING':
                    await gateway.ensure_ready()
                else:
                    with self.assertRaises(GatewayError):
                        await gateway.ensure_ready()
        for code in [401, 403, 503]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(code))) as client:
                with self.assertRaises(GatewayError):
                    await WhatsAppGateway(settings(), client).status()

    async def test_pair_creates_session_and_saves_qr(self):
        calls = []
        png = b'\x89PNG\r\n\x1a\nfixture'
        def handler(request):
            calls.append(request)
            if request.method == 'POST':
                self.assertEqual(json.loads(request.content)['name'], 'default')
                self.assertTrue(json.loads(request.content)['start'])
                return httpx.Response(201, json={'status': 'STARTING'})
            if request.url.path.endswith('/auth/qr'):
                return httpx.Response(200, json={'mimetype': 'image/png', 'data': base64.b64encode(png).decode()})
            if len(calls) == 1:
                return httpx.Response(404)
            return httpx.Response(200, json={'status': 'SCAN_QR_CODE'})
        with TemporaryDirectory() as tmp:
            qr = Path(tmp) / 'qr.png'
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with contextlib.redirect_stdout(io.StringIO()):
                    await WhatsAppGateway(settings(), client).pair(qr)
            self.assertEqual(qr.read_bytes(), png)
            self.assertEqual(qr.stat().st_mode & 0o777, 0o600)
        self.assertEqual([r.method for r in calls], ['GET', 'POST', 'GET', 'GET'])

    async def test_pair_already_working_and_stopped(self):
        for initial in ['WORKING', 'STOPPED', 'FAILED']:
            calls = []
            def handler(request):
                calls.append(request)
                if request.method == 'POST':
                    action = 'restart' if initial == 'FAILED' else 'start'
                    self.assertEqual(request.url.path, f'/api/sessions/default/{action}')
                    return httpx.Response(201)
                return httpx.Response(200, json={'status': initial if len(calls) == 1 else 'WORKING'})
            with TemporaryDirectory() as tmp:
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with contextlib.redirect_stdout(io.StringIO()):
                        await WhatsAppGateway(settings(), client).pair(Path(tmp) / 'qr.png')
                self.assertFalse((Path(tmp) / 'qr.png').exists())
            self.assertEqual(sum(r.method == 'POST' for r in calls), 0 if initial == 'WORKING' else 1)

    async def test_send_ambiguous_vs_no_connection_and_no_retries(self):
        for error, expected in [(httpx.ReadTimeout, AmbiguousSend), (httpx.WriteError, AmbiguousSend),
                                (httpx.ConnectError, RejectedSend), (httpx.ConnectTimeout, RejectedSend)]:
            calls = []
            def handler(request):
                calls.append(request)
                raise error('simulated', request=request)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(expected):
                    await WhatsAppGateway(settings(), client).send_text('Hi', '+32470111111')
            self.assertEqual(len(calls), 1)
        for result in [{}, [], {'id': None}, {'id': ''}, {'id': {'_serialized': 'id'}}]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(201, json=result))) as client:
                with self.assertRaises(AmbiguousSend):
                    await WhatsAppGateway(settings(), client).send_text('Hi', '+32470111111')

    async def test_unpaired_scan_never_claims_deliveries(self):
        from app.models import Property
        class FakeScraper:
            def __init__(self, *args): pass
            async def search(self, config):
                return [Property('immoweb', '1', 'https://example.com/1')]
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'status': 'SCAN_QR_CODE'})
        db = Database(':memory:')
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch.dict('app.main.SCRAPERS', {'immoweb': FakeScraper}):
                    with self.assertRaises(GatewayError):
                        await scan(settings(), client, db, False)
            self.assertEqual(db.conn.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 0)
            self.assertEqual([r.method for r in requests], ['GET'])
        finally:
            db.close()

    async def test_ambiguous_send_does_not_repeat_after_next_scan(self):
        from app.models import Property
        class FakeScraper:
            def __init__(self, *args): pass
            async def search(self, config):
                return [Property('immoweb', '1', 'https://example.com/1')]
        posts = []
        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'status': 'WORKING'})
            posts.append(json.loads(request.content)['chatId'])
            if len(posts) == 1:
                raise httpx.ReadTimeout('simulated lost response', request=request)
            return httpx.Response(201, json={'id': 'true_32470222222@c.us_ID'})
        db = Database(':memory:')
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch.dict('app.main.SCRAPERS', {'immoweb': FakeScraper}):
                    self.assertFalse(await scan(settings(), client, db, False))
                    await scan(settings(), client, db, False)
            self.assertEqual(posts, ['32470111111@c.us', '32470222222@c.us'])
            self.assertEqual(db.conn.execute('SELECT state FROM deliveries ORDER BY recipient').fetchall(), [('unknown',), ('accepted',)])
        finally:
            db.close()
