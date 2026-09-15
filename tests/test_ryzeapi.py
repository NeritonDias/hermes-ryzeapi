import asyncio, copy, importlib.util, json, sys, tempfile, time, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ryzeapi', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules['ryzeapi'] = module
spec.loader.exec_module(module)
from ryzeapi.core import Inbox, normalize, allowed_numbers, phone
from ryzeapi.client import RyzeClient, RyzeError

OWNER = '5511999999999'

def event():
    return {'event': 'message.exchange', 'instanceData': {'instance': 'hermes-test', 'token': 'DO-NOT-STORE'},
        'data': {'message': {'id': 'test-message', 'direction': 'incoming',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'chat': {'jid': OWNER, 'type': 'private'}, 'sender': {'jid': OWNER},
            'content': {'text': 'Olá Hermes'}}}}

def norm(value): return normalize(value, instance='hermes-test', allowed={OWNER})

class EnvelopeTests(unittest.TestCase):
    def test_valid_and_no_secret(self):
        item = norm(event())
        self.assertEqual(item['number'], OWNER)
        self.assertNotIn('DO-NOT-STORE', json.dumps(item))
        self.assertNotIn('instanceData', item)

    def test_wrong_instance(self):
        value = event(); value['instanceData']['instance'] = 'retired'
        self.assertIsNone(norm(value))

    def test_outgoing(self):
        value = event(); value['data']['message']['direction'] = 'outgoing'
        self.assertIsNone(norm(value))

    def test_unknown_sender(self):
        value = event(); value['data']['message']['sender']['jid'] = '5511888888888'
        self.assertIsNone(norm(value))

    def test_mismatched_chat(self):
        value = event(); value['data']['message']['chat']['jid'] = '5511888888888'
        self.assertIsNone(norm(value))

    def test_group(self):
        value = event(); value['data']['message']['chat']['type'] = 'group'
        self.assertIsNone(norm(value))

    def test_replay_old_future_and_no_zone(self):
        for stamp in [(datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),
                      (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), '2026-09-15T02:00:00']:
            value = event(); value['data']['message']['timestamp'] = stamp
            self.assertIsNone(norm(value))

    def test_wrong_shapes(self):
        for value in [None, [], 'x', {}, {'event': 'message.exchange', 'instanceData': []}, {'data': None}]:
            self.assertIsNone(norm(value))
        for field in ['type', 'media']:
            value = event()
            value['data']['message'][field] = [] if field == 'type' else {'type': []}
            self.assertIsNone(norm(value))

    def test_url_only_media_rejected(self):
        value = event(); value['data']['message']['media'] = {'type': 'image', 'mimetype': 'image/png', 'url': 'http://169.254.169.254'}
        self.assertIsNone(norm(value))

    def test_bad_and_valid_base64(self):
        import base64
        value = event(); value['data']['message']['media'] = {'type': 'ptt', 'mimetype': 'audio/ogg', 'base64': '%%%'}
        self.assertIsNone(norm(value))
        value['data']['message']['media']['base64'] = base64.b64encode(b'OggS-test').decode()
        self.assertEqual(norm(value)['media']['kind'], 'ptt')

    def test_empty_allowlist_not_open(self):
        for val in ['', '*', 'any', OWNER+',*']:
            with self.assertRaises(ValueError): allowed_numbers(val)

    def test_phone_does_not_convert_groups_or_lids(self):
        self.assertEqual(phone(OWNER+'@s.whatsapp.net'), OWNER)
        self.assertEqual(phone('1201234@g.us'), '')
        self.assertEqual(phone('123456789@lid'), '')

class InboxTests(unittest.TestCase):
    def test_dedup_persistence_and_uncertain_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'inbox.db'
            inbox = Inbox(path)
            self.assertEqual(inbox.put(norm(event())), 'queued')
            self.assertEqual(inbox.put(norm(event())), 'duplicate')
            self.assertEqual(inbox.take()['id'], 'test-message')
            inbox.close()
            inbox = Inbox(path)
            self.assertIsNone(inbox.take())
            self.assertEqual(inbox.db.execute('SELECT status,payload FROM inbox').fetchone(), ('uncertain','{}'))
            inbox.close()

    def test_queue_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            inbox = Inbox(Path(temp)/'inbox.db')
            for index in range(100):
                item = norm(event()); item['id'] = str(index)
                self.assertEqual(inbox.put(item), 'queued')
            item['id'] = 'overflow'
            self.assertEqual(inbox.put(item), 'full')
            inbox.close()

    def test_admitted_scrubs_content(self):
        with tempfile.TemporaryDirectory() as temp:
            inbox = Inbox(Path(temp)/'inbox.db')
            inbox.put(norm(event())); inbox.take(); inbox.finish('test-message', True)
            self.assertEqual(inbox.db.execute('SELECT payload FROM inbox').fetchone()[0], '{}')
            inbox.close()

class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_contract(self):
        async def transport(req):
            self.assertEqual(str(req.url), 'https://ryzeapi.cloud/api/message/text/hermes-test')
            self.assertEqual(req.headers['token'], 'test-token')
            self.assertEqual(json.loads(req.content), {'number': OWNER, 'message': 'hello', 'linkPreview': False, 'replyTo': 'original'})
            return httpx.Response(200, json={'success': True, 'data': {'messageId': 'sent-1'}})
        client = RyzeClient('hermes-test', 'test-token', transport=httpx.MockTransport(transport))
        self.assertEqual(await client.send_text(OWNER, 'hello', 'original'), 'sent-1')
        await client.close()

    async def test_failure_does_not_expose_token(self):
        client = RyzeClient('hermes-test', 'test-token', transport=httpx.MockTransport(lambda req:
            httpx.Response(401, json={'error': {'message': 'test-token'}})))
        with self.assertRaises(RyzeError) as ctx: await client.send_text(OWNER, 'hello')
        self.assertNotIn('test-token', str(ctx.exception))
        await client.close()

    async def test_no_redirect_or_retry(self):
        calls = []
        def handler(req):
            calls.append(req)
            return httpx.Response(302, headers={'Location': 'https://evil.example'})
        client = RyzeClient('hermes-test', 'test-token', transport=httpx.MockTransport(handler))
        with self.assertRaises(RyzeError): await client.send_text(OWNER, 'hello')
        self.assertEqual(len(calls), 1)
        await client.close()

    async def test_timeout_no_retry(self):
        calls=[]
        def handler(req): calls.append(req); raise httpx.ReadTimeout('hidden')
        client = RyzeClient('hermes-test', 'test-token', transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(RyzeError, 'uncertain'): await client.send_text(OWNER, 'hello')
        self.assertEqual(len(calls),1)
        await client.close()

    async def test_no_false_success(self):
        client = RyzeClient('hermes-test', 'test-token', transport=httpx.MockTransport(lambda req:
            httpx.Response(200, json={'success': True, 'data': {}})))
        with self.assertRaises(RyzeError): await client.send_text(OWNER, 'hello')
        await client.close()

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from ryzeapi.adapter import RyzeAdapter
        from gateway.config import PlatformConfig
        class Context:
            def register_platform(self, **kwargs):
                from gateway.platform_registry import PlatformEntry, platform_registry
                platform_registry.register(PlatformEntry(**kwargs))
        module.register(Context())
        self.adapter = RyzeAdapter(PlatformConfig())
        self.temp = tempfile.TemporaryDirectory()
        self.adapter.instance = 'hermes-test'
        self.adapter.secret = 's'*40
        self.adapter.allowed = {OWNER}
        self.adapter.recipients = {OWNER}
        from unittest.mock import patch
        self.settings_patch = patch('ryzeapi.adapter.load', return_value={'enabled': True,
            'instance': 'hermes-test', 'webhook_secret': 's'*40, 'allowed_users': OWNER, 'buffer_seconds': 0})
        self.settings_patch.start()
        from unittest.mock import AsyncMock
        self.adapter.transcribe_voice = AsyncMock(return_value='Transcrição sintética')
        self.adapter.inbox = Inbox(Path(self.temp.name)/'inbox.db')

    async def asyncTearDown(self):
        self.settings_patch.stop()
        self.adapter.inbox.close(); self.temp.cleanup()

    async def test_pause_blocks_stale_running_adapter(self):
        from unittest.mock import patch
        class Request:
            headers = {'Authorization': 'Bearer '+'s'*40}
        with patch('ryzeapi.adapter.load', return_value={'enabled': False}):
            self.assertEqual((await self.adapter.webhook(Request())).status, 503)
            self.assertFalse((await self.adapter.send(OWNER, 'hello')).success)

    async def test_webhook_auth_and_enqueue(self):
        class Request:
            headers = {}; content_type = 'application/json'
            async def json(self): return event()
        request = Request()
        self.assertEqual((await self.adapter.webhook(request)).status,401)
        request.headers = {'Authorization': 'Bearer '+'s'*40}
        self.assertEqual((await self.adapter.webhook(request)).status,202)
        self.assertEqual((await self.adapter.webhook(request)).status,202)
        self.assertEqual(self.adapter.inbox.db.execute('SELECT count(*) FROM inbox').fetchone()[0],1)

    async def test_send_allowlist(self):
        result = await self.adapter.send('5511888888888','hello')
        self.assertFalse(result.success)

    async def test_outbound_firewall_is_separate_from_command_allowlist(self):
        from unittest.mock import patch, AsyncMock
        friend='5511888888888'
        self.adapter.recipients={OWNER,friend}
        self.adapter.client=AsyncMock()
        self.adapter.client.send_text.return_value='sent-fixture'
        with patch('ryzeapi.adapter.load',return_value={'enabled':True,'instance':'hermes-test',
                'webhook_secret':'s'*40,'allowed_users':OWNER,'allowed_recipients':OWNER+','+friend}):
            self.assertTrue((await self.adapter.send(friend,'authorized reply')).success)
            self.assertFalse((await self.adapter.send('5511777777777','blocked')).success)
            value=event(); value['data']['message']['sender']['jid']=friend; value['data']['message']['chat']['jid']=friend
            self.assertIsNone(normalize(value,instance=self.adapter.instance,allowed=self.adapter.allowed))
        self.assertEqual(self.adapter.client.send_text.await_count,1)

    async def test_revoking_recipient_blocks_stale_adapter(self):
        from unittest.mock import patch, AsyncMock
        self.adapter.client=AsyncMock()
        self.adapter.recipients={OWNER,'5511888888888'}
        with patch('ryzeapi.adapter.load',return_value={'enabled':True,'instance':'hermes-test',
                'webhook_secret':'s'*40,'allowed_users':OWNER,'allowed_recipients':OWNER}):
            self.assertFalse((await self.adapter.send('5511888888888','blocked')).success)
        self.adapter.client.send_text.assert_not_awaited()

    async def test_revocation_blocks_remaining_message_parts(self):
        from unittest.mock import patch, AsyncMock
        value={'enabled':True,'instance':'hermes-test','webhook_secret':'s'*40,'allowed_users':OWNER}
        async def sent(*args): value['enabled']=False; return 'first-part'
        self.adapter.client=AsyncMock()
        self.adapter.client.send_text.side_effect=sent
        with patch('ryzeapi.adapter.load',return_value=value):
            self.assertFalse((await self.adapter.send(OWNER,'a'*9000)).success)
        self.assertEqual(self.adapter.client.send_text.await_count,1)

    async def test_real_http_contract(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer, TestClient
        app = web.Application(client_max_size=1024)
        app.router.add_post('/ryzeapi/events', self.adapter.webhook)
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/ryzeapi/events', json=event())
            self.assertEqual(response.status, 401)
            headers={'Authorization': 'Bearer '+self.adapter.secret}
            response = await client.post('/ryzeapi/events', json=event(), headers=headers)
            self.assertEqual(response.status, 202)
            response = await client.post('/ryzeapi/events', data='bad', headers=headers)
            self.assertEqual(response.status, 415)
            headers['Content-Type']='application/json'
            response = await client.post('/ryzeapi/events', data='{bad', headers=headers)
            self.assertEqual(response.status, 400)
            response = await client.post('/ryzeapi/events', data='x'*2048, headers=headers)
            self.assertEqual(response.status, 413)

    async def test_real_event_handoff(self):
        received=[]
        async def handle(event):
            received.append(event)
            event._gateway_accepted=True
            self.adapter._running=False
        self.adapter.handle_message=handle
        self.adapter.inbox.put(norm(event()))
        self.adapter._running=True
        await asyncio.wait_for(self.adapter.consume(), timeout=2)
        self.assertEqual(received[0].source.chat_id, OWNER)
        self.assertEqual(received[0].text, 'Olá Hermes')
        self.assertIsNone(received[0].raw_message)
        self.assertEqual(self.adapter.inbox.db.execute('SELECT status FROM inbox').fetchone()[0], 'admitted')

if __name__ == '__main__': unittest.main(verbosity=2)
